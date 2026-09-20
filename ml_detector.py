"""
ml_detector.py

Step 2: Pull transaction + account data from MySQL, compute features
(the same signals your rule-based detector.py uses), and split into
train/test sets. Training comes in the next step.
"""

import mysql.connector
import pandas as pd
from sklearn.model_selection import train_test_split

con = mysql.connector.connect(
    host="localhost",
    user="root",
    password="root",
    database="bank_system"
)
cursor = con.cursor()

# Same join style as detector.py, but now also pulling is_fraud as our label.
cursor.execute("""
    SELECT
        t.transaction_id,
        t.sender_id,
        t.amount,
        t.timestamp,
        t.location,
        a.avg_transaction_amount,
        a.created_at,
        prev.location AS prev_location,
        prev.timestamp AS prev_timestamp,
        t.is_fraud
    FROM transactions t
    JOIN accounts a ON t.sender_id = a.account_id
    LEFT JOIN transactions prev
        ON prev.sender_id = t.sender_id
        AND prev.timestamp < t.timestamp
        AND prev.timestamp = (
            SELECT MAX(timestamp) FROM transactions
            WHERE sender_id = t.sender_id AND timestamp < t.timestamp
        )
""")
rows = cursor.fetchall()
cols = ["transaction_id", "sender_id", "amount", "timestamp", "location",
        "avg_transaction_amount", "created_at", "prev_location", "prev_timestamp", "is_fraud"]
df = pd.DataFrame(rows, columns=cols)

print(f"Pulled {len(df)} transactions from the database.")

cities = {
    "Mumbai-Pune": 150, "Bangalore-Surat": 1250, "Bangalore-Mumbai": 980,
    "Bangalore-Pune": 840, "Mumbai-Surat": 280, "Surat-Pune": 420
}

def distance_between(loc1, loc2):
    if loc1 == loc2:
        return 0
    pair = f"{loc1}-{loc2}"
    rev = f"{loc2}-{loc1}"
    return cities.get(pair) or cities.get(rev) or 0

def build_features(row):
    hour = row["timestamp"].hour
    amount = float(row["amount"])
    avg_amount = float(row["avg_transaction_amount"]) if row["avg_transaction_amount"] else 0
    account_age_days = (row["timestamp"] - row["created_at"]).total_seconds() / 86400

    if pd.notnull(row["prev_timestamp"]):
        dist = distance_between(row["location"], row["prev_location"])
        minutes_since_prev = (row["timestamp"] - row["prev_timestamp"]).total_seconds() / 60
    else:
        dist = 0
        minutes_since_prev = 99999  # no previous transaction -> treat as "long ago"

    return pd.Series({
        "amount": amount,
        "hour": hour,
        "amount_vs_avg_ratio": (amount / avg_amount) if avg_amount > 0 else 0,
        "account_age_days": account_age_days,
        "distance_from_prev_km": dist,
        "minutes_since_prev_txn": minutes_since_prev,
    })

features = df.apply(build_features, axis=1)
labels = df["is_fraud"]

X_train, X_test, y_train, y_test = train_test_split(
    features, labels, test_size=0.25, random_state=42, stratify=labels
)

print(f"Training set: {len(X_train)} rows | Test set: {len(X_test)} rows")
print(f"Fraud rate in training set: {y_train.mean():.2%}")
print(f"Fraud rate in test set: {y_test.mean():.2%}")

cursor.close()
con.close()