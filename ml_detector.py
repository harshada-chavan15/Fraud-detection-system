"""
ml_detector.py

Trains a Decision Tree on the labeled transactions (is_fraud) and compares it
against the rule engine (the status that detector.py saved), on the SAME test rows.

BEFORE RUNNING (in this order):
    python generate_data.py      # fresh labeled data (also wipes dashboard test rows)
    python detector.py           # rule engine scores everything and saves status
    python ml_detector.py

Important design choices (be ready to explain these):
  * The tree NEVER sees risk_score or status. Those come from the rules, and
    feeding them in would be cheating (data leakage).
  * The rules are treated as "said fraud" when status is FLAGGED or BLOCKED.
  * One split is noisy on ~170 test rows, so we also repeat over 10 random splits.
  * The data is synthetic, so the numbers show the pipeline works, not real-world accuracy.

Results are also saved to ml_results.txt for your README.
"""

import os

import mysql.connector
import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier, export_text

from risk_engine import distance_between

FEATURES = [
    "amount",
    "hour",
    "amount_vs_avg_ratio",
    "account_age_days",
    "distance_from_prev_km",
    "minutes_since_prev_txn",
    "txns_last_min",
]

MAIN_SEED = 42
MAIN_DEPTH = 4
DEPTHS_TO_TRY = [2, 3, 4, 6]
SEEDS = list(range(10))

LINES = []  # everything printed is also collected here and saved to ml_results.txt


def out(text=""):
    print(text)
    LINES.append(str(text))


# ---------------------------------------------------------------------------
# 1. Load and clean the data
# ---------------------------------------------------------------------------
def load_data():
    con = mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "root"),
        database=os.environ.get("DB_NAME", "bank_system"),
    )
    cursor = con.cursor()
    cursor.execute(
        """
        SELECT
            t.transaction_id, t.sender_id, t.amount, t.timestamp, t.location,
            a.avg_transaction_amount, a.created_at,
            prev.location  AS prev_location,
            prev.timestamp AS prev_timestamp,
            t.is_fraud, t.status, t.risk_score
        FROM transactions t
        JOIN accounts a ON t.sender_id = a.account_id
        LEFT JOIN transactions prev
            ON prev.sender_id = t.sender_id
            AND prev.transaction_id != t.transaction_id
            AND prev.timestamp = (
                SELECT MAX(timestamp) FROM transactions
                WHERE sender_id = t.sender_id AND timestamp < t.timestamp
            )
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    con.close()
    cols = ["transaction_id", "sender_id", "amount", "timestamp", "location",
            "avg_transaction_amount", "created_at", "prev_location", "prev_timestamp",
            "is_fraud", "status", "risk_score"]
    return pd.DataFrame(rows, columns=cols)


def prepare(df):
    # The JOIN can return one transaction twice when two earlier transactions share
    # the same timestamp. Duplicates would land in BOTH train and test (leakage).
    df = df.drop_duplicates("transaction_id").reset_index(drop=True)
    for col in ["timestamp", "created_at", "prev_timestamp"]:
        df[col] = pd.to_datetime(df[col])
    df["amount"] = df["amount"].astype(float)
    df["avg_transaction_amount"] = df["avg_transaction_amount"].fillna(0).astype(float)
    df["is_fraud"] = df["is_fraud"].fillna(0).astype(int)
    return df


# ---------------------------------------------------------------------------
# 2. Features (the same signals the rules use, as numbers the tree can split on)
# ---------------------------------------------------------------------------
def velocity(df):
    """Transactions by the same sender in the 1 minute up to each transaction
    (including itself). Same definition the rule engine uses."""
    counts = pd.Series(0, index=df.index, dtype=int)
    epoch = pd.Timestamp("1970-01-01")
    for _, g in df.groupby("sender_id"):
        secs = (g["timestamp"] - epoch).dt.total_seconds().to_numpy()
        ordered = np.sort(secs)
        upper = np.searchsorted(ordered, secs, side="right")
        lower = np.searchsorted(ordered, secs - 60, side="left")
        counts.loc[g.index] = upper - lower
    return counts


def build_features(df):
    feat = pd.DataFrame(index=df.index)
    feat["amount"] = df["amount"]
    feat["hour"] = df["timestamp"].dt.hour

    avg = df["avg_transaction_amount"].replace(0, np.nan)
    feat["amount_vs_avg_ratio"] = (df["amount"] / avg).fillna(0)

    feat["account_age_days"] = (df["timestamp"] - df["created_at"]).dt.total_seconds() / 86400

    feat["distance_from_prev_km"] = [
        distance_between(loc, prev) if isinstance(prev, str) else 0
        for loc, prev in zip(df["location"], df["prev_location"])
    ]
    # No previous transaction -> treat as "a very long time ago"
    feat["minutes_since_prev_txn"] = (
        (df["timestamp"] - df["prev_timestamp"]).dt.total_seconds() / 60
    ).fillna(99999)

    feat["txns_last_min"] = velocity(df)
    return feat[FEATURES]


# ---------------------------------------------------------------------------
# 3. Train + evaluate
# ---------------------------------------------------------------------------
def metrics(y_true, y_pred):
    return {
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall": recall_score(y_true, y_pred, zero_division=0),
        "f1": f1_score(y_true, y_pred, zero_division=0),
    }


def fmt(m):
    return f"precision {m['precision']:.2f} | recall {m['recall']:.2f} | F1 {m['f1']:.2f}"


def run_once(features, labels, rule_pred, seed, depth):
    X_train, X_test, y_train, y_test = train_test_split(
        features, labels, test_size=0.25, random_state=seed, stratify=labels
    )
    tree = DecisionTreeClassifier(max_depth=depth, class_weight="balanced", random_state=seed)
    tree.fit(X_train, y_train)
    tree_pred = tree.predict(X_test)
    rules_on_test = rule_pred.loc[X_test.index]
    return {
        "tree": tree,
        "X_test": X_test,
        "y_test": y_test,
        "tree_pred": tree_pred,
        "rule_pred": rules_on_test,
        "tree_m": metrics(y_test, tree_pred),
        "rules_m": metrics(y_test, rules_on_test),
    }


def show_confusion(name, y_true, y_pred):
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    out(f"  {name}: caught fraud {tp} | missed fraud {fn} | false alarms {fp} | correctly cleared {tn}")


def main():
    df = prepare(load_data())

    if (df["status"] == "pending").any():
        out("Some transactions are still 'pending'. Run  python detector.py  first, then re-run this.")
        return

    features = build_features(df)
    labels = df["is_fraud"]
    rule_pred = df["status"].isin(["FLAGGED", "BLOCKED"]).astype(int)

    out("==== DATA ====")
    out(f"{len(df)} transactions | {int(labels.sum())} labeled fraud ({labels.mean():.1%})")
    out("Note: synthetic data. Rows entered through the dashboard count as legit (is_fraud=0).")

    # ---- main run ----
    res = run_once(features, labels, rule_pred, MAIN_SEED, MAIN_DEPTH)
    y_test = res["y_test"]
    out(f"\n==== MAIN RUN (seed {MAIN_SEED}, tree depth {MAIN_DEPTH}, {len(y_test)} test rows) ====")
    out("Rules (FLAGGED or BLOCKED counts as 'fraud'):")
    out("  " + fmt(res["rules_m"]))
    show_confusion("rules", y_test, res["rule_pred"])
    out("Decision Tree:")
    out("  " + fmt(res["tree_m"]))
    show_confusion("tree ", y_test, res["tree_pred"])

    # ---- what the tree learned ----
    tree = res["tree"]
    out("\n==== WHAT THE TREE LEARNED ====")
    out("Feature importance:")
    for name, imp in sorted(zip(FEATURES, tree.feature_importances_), key=lambda x: -x[1]):
        if imp > 0:
            out(f"  {name}: {imp:.2f}")
    out("\nThe tree's if/else rules (class 1 = fraud):")
    out(export_text(tree, feature_names=FEATURES))

    # ---- where they disagree ----
    test = df.loc[y_test.index, ["transaction_id", "amount", "location", "is_fraud"]].copy()
    test["hour"] = res["X_test"]["hour"]
    test["tree_pred"] = res["tree_pred"]
    test["rule_pred"] = res["rule_pred"]
    fraud = test[test["is_fraud"] == 1]
    legit = test[test["is_fraud"] == 0]

    groups = [
        ("Fraud caught by the TREE but missed by the rules", fraud[(fraud.tree_pred == 1) & (fraud.rule_pred == 0)]),
        ("Fraud caught by the RULES but missed by the tree", fraud[(fraud.rule_pred == 1) & (fraud.tree_pred == 0)]),
        ("Fraud missed by BOTH (likely the undetectable 'stealth' fraud)", fraud[(fraud.rule_pred == 0) & (fraud.tree_pred == 0)]),
        ("Legit transactions wrongly stopped by the rules only", legit[(legit.rule_pred == 1) & (legit.tree_pred == 0)]),
        ("Legit transactions wrongly stopped by the tree only", legit[(legit.tree_pred == 1) & (legit.rule_pred == 0)]),
    ]
    out("\n==== WHERE THEY DISAGREE (test rows) ====")
    for title, rows in groups:
        out(f"{title}: {len(rows)}")
        for _, r in rows.head(3).iterrows():
            out(f"    #{int(r.transaction_id)}  Rs{r.amount:,.0f}  {r.location}  hour {int(r.hour)}")

    # ---- robustness: repeat over many splits ----
    out(f"\n==== ROBUSTNESS: {len(SEEDS)} different random splits, depth {MAIN_DEPTH} ====")
    tree_runs, rule_runs = [], []
    for s in SEEDS:
        r = run_once(features, labels, rule_pred, s, MAIN_DEPTH)
        tree_runs.append(r["tree_m"])
        rule_runs.append(r["rules_m"])

    def summarize(name, runs):
        parts = []
        for k in ["precision", "recall", "f1"]:
            vals = [m[k] for m in runs]
            parts.append(f"{k} {np.mean(vals):.2f} +/- {np.std(vals):.2f}")
        out(f"  {name}: " + " | ".join(parts))

    summarize("rules", rule_runs)
    summarize("tree ", tree_runs)

    # ---- tree depth comparison ----
    out("\n==== TREE DEPTH COMPARISON (average over the same splits) ====")
    for d in DEPTHS_TO_TRY:
        runs = [run_once(features, labels, rule_pred, s, d)["tree_m"] for s in SEEDS]
        out(f"  depth {d}: precision {np.mean([m['precision'] for m in runs]):.2f} | "
            f"recall {np.mean([m['recall'] for m in runs]):.2f} | "
            f"F1 {np.mean([m['f1'] for m in runs]):.2f}")

    with open("ml_results.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LINES))
    out("\nSaved these results to ml_results.txt")


if __name__ == "__main__":
    main()
