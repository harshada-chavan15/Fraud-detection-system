"""
detector.py

Batch scorer. Scores every 'pending' transaction with risk_engine, processes
them highest-risk first using a heap (a priority review queue), and SAVES the
result (status, risk_score, reasons) back to MySQL.

Run:
    python detector.py            # score all pending transactions
    python detector.py --rescore  # reset everything to pending, then score again
                                  # (use this after you change thresholds)
"""

import heapq
import os
import sys

import mysql.connector

from risk_engine import score_transaction, decide, count_recent


def get_connection():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "root"),
        database=os.environ.get("DB_NAME", "bank_system"),
    )


PENDING_QUERY = """
    SELECT
        t.transaction_id,
        t.sender_id,
        t.amount,
        t.timestamp,
        t.location,
        a.customer_name,
        a.avg_transaction_amount,
        a.created_at,
        prev.location  AS prev_location,
        prev.timestamp AS prev_timestamp
    FROM transactions t
    JOIN accounts a ON t.sender_id = a.account_id
    LEFT JOIN transactions prev
        ON prev.sender_id = t.sender_id
        AND prev.transaction_id != t.transaction_id
        AND prev.timestamp = (
            SELECT MAX(timestamp) FROM transactions
            WHERE sender_id = t.sender_id AND timestamp < t.timestamp
        )
    WHERE t.status = 'pending'
"""


def run_detection():
    con = get_connection()
    cursor = con.cursor()

    if "--rescore" in sys.argv:
        cursor.execute("UPDATE transactions SET status = 'pending', risk_score = NULL, reasons = NULL")
        con.commit()
        print("Reset all transactions to pending.")

    cursor.execute(PENDING_QUERY)
    rows = cursor.fetchall()

    # If two earlier transactions share the exact same timestamp, the JOIN returns
    # the same transaction twice. Keep one row per transaction_id.
    unique_rows = {}
    for row in rows:
        unique_rows.setdefault(row[0], row)
    rows = list(unique_rows.values())

    print(f"Fetched {len(rows)} pending transactions")
    if not rows:
        cursor.close()
        con.close()
        return

    # Score everything and push into a min-heap using NEGATIVE risk, so the
    # highest-risk transaction is popped first.
    heap = []
    for row in rows:
        (txn_id, sender_id, amount, ts, location, name,
         avg_amount, created_at, prev_location, prev_ts) = row

        txn = {
            "amount": amount,
            "timestamp": ts,
            "location": location,
            "avg_amount": avg_amount,
            "account_created_at": created_at,
        }
        prev = {"location": prev_location, "timestamp": prev_ts} if prev_location else None

        recent = count_recent(cursor, sender_id, ts)
        score, reasons = score_transaction(txn, prev, recent)
        heapq.heappush(heap, (-score, txn_id, name, float(amount), reasons))

    # Pop in priority order: highest risk first.
    updates = []
    counts = {"BLOCKED": 0, "FLAGGED": 0, "APPROVED": 0}
    print("\n==== TOP 10 HIGHEST-RISK TRANSACTIONS ====")
    shown = 0
    while heap:
        neg_score, txn_id, name, amount, reasons = heapq.heappop(heap)
        score = -neg_score
        action = decide(score)
        counts[action] += 1
        updates.append((action, score, ", ".join(reasons), txn_id))

        if shown < 10:
            print(f"#{txn_id} {name} Rs{amount:,.2f} score={score} {action} | {', '.join(reasons) or '-'}")
            shown += 1

    cursor.executemany(
        "UPDATE transactions SET status = %s, risk_score = %s, reasons = %s WHERE transaction_id = %s",
        updates,
    )
    con.commit()

    print("\n==== SUMMARY ====")
    print(f"BLOCKED: {counts['BLOCKED']} | FLAGGED: {counts['FLAGGED']} | APPROVED: {counts['APPROVED']}")
    print("Results saved to the database.")

    cursor.close()
    con.close()


if __name__ == "__main__":
    run_detection()
