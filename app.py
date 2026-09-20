"""
app.py

Flask dashboard. When you submit a transaction it is:
  1. validated,
  2. inserted as 'pending',
  3. scored by risk_engine (the SAME rules detector.py uses),
  4. saved with its status, risk score and reasons,
and then the page redirects back to the dashboard.

Run:  python app.py   ->  http://127.0.0.1:5000
"""

import os

import config  # loads settings from .env
import mysql.connector
from flask import Flask, redirect, render_template, request, url_for

from risk_engine import count_recent, decide, score_transaction

app = Flask(__name__)

CITIES = ["Mumbai", "Pune", "Surat", "Bangalore"]


def get_db():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "root"),
        database=os.environ.get("DB_NAME", "bank_system"),
    )


# Everything the rule engine needs for ONE transaction: its own details, the
# account's details, and the sender's previous transaction (if any).
SCORE_QUERY = """
    SELECT
        t.sender_id,
        t.amount,
        t.timestamp,
        t.location,
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
    WHERE t.transaction_id = %s
    LIMIT 1
"""


def account_exists(cursor, account_id):
    cursor.execute("SELECT 1 FROM accounts WHERE account_id = %s", (account_id,))
    return cursor.fetchone() is not None


def score_and_save(con, cursor, txn_id):
    """Score one transaction with risk_engine and write the result back."""
    cursor.execute(SCORE_QUERY, (txn_id,))
    row = cursor.fetchone()
    if row is None:
        return

    sender_id, amount, ts, location, avg_amount, created_at, prev_location, prev_ts = row

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
    action = decide(score)

    cursor.execute(
        "UPDATE transactions SET status = %s, risk_score = %s, reasons = %s WHERE transaction_id = %s",
        (action, score, ", ".join(reasons), txn_id),
    )
    con.commit()


def handle_submission(con, cursor):
    """Validate the form, insert the transaction, score it.
    Returns an error message (string) if something is wrong, otherwise None."""
    try:
        sender_id = int(request.form["sender_id"])
        receiver_id = int(request.form["receiver_id"])
        amount = float(request.form["amount"])
    except (KeyError, ValueError):
        return "Please enter valid numbers for sender, receiver and amount."

    location = request.form.get("location", "").strip()

    if amount <= 0:
        return "Amount must be greater than zero."
    if location not in CITIES:
        return "Please choose a city from the list: " + ", ".join(CITIES) + "."
    if sender_id == receiver_id:
        return "Sender and receiver must be different accounts."
    if not account_exists(cursor, sender_id):
        return f"Sender account {sender_id} does not exist."
    if not account_exists(cursor, receiver_id):
        return f"Receiver account {receiver_id} does not exist."

    cursor.execute(
        """
        INSERT INTO transactions (sender_id, receiver_id, amount, location, status, timestamp)
        VALUES (%s, %s, %s, %s, 'pending', NOW())
        """,
        (sender_id, receiver_id, amount, location),
    )
    txn_id = cursor.lastrowid
    con.commit()

    score_and_save(con, cursor, txn_id)
    return None


def get_recent(cursor):
    cursor.execute(
        """
        SELECT transaction_id, sender_id, receiver_id, amount, location,
               risk_score, status, reasons
        FROM transactions
        ORDER BY timestamp DESC, transaction_id DESC
        LIMIT 10
        """
    )
    results = []
    for r in cursor.fetchall():
        results.append({
            "id": r[0],
            "sender_id": r[1],
            "receiver_id": r[2],
            "amount": float(r[3]),
            "location": r[4],
            "risk_score": r[5] if r[5] is not None else 0,
            "status": r[6],
            "reasons": r[7] or "",
        })
    return results


@app.route("/", methods=["GET", "POST"])
def home():
    error = None
    con = get_db()
    cursor = con.cursor(buffered=True)
    try:
        if request.method == "POST":
            error = handle_submission(con, cursor)
            if error is None:
                # Post/Redirect/Get: refreshing the page will NOT resubmit the form.
                return redirect(url_for("home"))
        results = get_recent(cursor)
    finally:
        cursor.close()
        con.close()

    return render_template("index.html", transactions=results, error=error, cities=CITIES)


if __name__ == "__main__":
    app.run(debug=True)
