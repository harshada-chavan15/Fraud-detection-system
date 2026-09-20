"""
generate_data.py

Generates randomized transaction data for the fraud detection project, with an
independent `is_fraud` ground-truth label (separate from the rule-based
risk_score/status columns produced by the rule engine).

What this script does:
  1. Adds any missing columns (is_fraud, risk_score, reasons) to `transactions`.
  2. Optionally clears old transactions so you start from clean data.
  3. Makes sure there are at least MIN_ACCOUNTS accounts (old + brand-new mix).
  4. Generates normal, fraud, and tricky edge-case transactions.
  5. Injects rapid-fire bursts (some fraud, some legit).
  6. Guarantees no transaction happens before its account existed, or in the future.
  7. Runs a self-check at the end and prints OK / PROBLEM.
"""

import os
import random
from datetime import datetime, timedelta

import mysql.connector

random.seed(42)  # reproducible dataset -- remove/change for fresh data each run

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
CLEAR_OLD_TRANSACTIONS = True   # deletes ALL existing rows in `transactions` first
MIN_ACCOUNTS = 20               # only creates accounts if fewer than this exist
NUM_TRANSACTIONS = 600          # normal + fraud + edge-case transactions
NUM_BURSTS = 20                 # rapid-fire groups of 3-5 transactions
DAYS_BACK = 14                  # how far back transactions can go

con = mysql.connector.connect(
    host=os.environ.get("DB_HOST", "localhost"),
    user=os.environ.get("DB_USER", "root"),
    password=os.environ.get("DB_PASSWORD", "root"),
    database=os.environ.get("DB_NAME", "bank_system"),
)
cursor = con.cursor()

now = datetime.now().replace(microsecond=0)


# ---------------------------------------------------------------------------
# 0. Make sure the needed columns exist on `transactions`.
# ---------------------------------------------------------------------------
def add_column_if_missing(table, column, definition):
    cursor.execute(
        """
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s
        """,
        (table, column),
    )
    if cursor.fetchone()[0] == 0:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        con.commit()
        print(f"Added column {table}.{column}")


add_column_if_missing("transactions", "is_fraud", "TINYINT DEFAULT 0")
add_column_if_missing("transactions", "risk_score", "INT DEFAULT NULL")
add_column_if_missing("transactions", "reasons", "VARCHAR(255) DEFAULT NULL")

if CLEAR_OLD_TRANSACTIONS:
    cursor.execute("DELETE FROM transactions")
    con.commit()
    print("Cleared old transactions.")

# ---------------------------------------------------------------------------
# 1. Accounts: mix of old and new accounts, varied spending habits.
# ---------------------------------------------------------------------------
cities = ["Mumbai", "Pune", "Surat", "Bangalore"]

first_names = ["Aarav", "Vihaan", "Ishaan", "Diya", "Ananya", "Kavya", "Rohan",
               "Meera", "Aditya", "Sneha", "Karan", "Priya", "Nikhil", "Tanya",
               "Rahul", "Simran", "Yash", "Pooja", "Arjun", "Neha"]
last_names = ["Sharma", "Verma", "Patel", "Reddy", "Iyer", "Kapoor", "Gupta",
              "Nair", "Joshi", "Mehta"]

cursor.execute("SELECT COUNT(*), MAX(account_id) FROM accounts")
existing_count, max_id = cursor.fetchone()
start_id = (max_id or 0) + 1
to_create = max(0, MIN_ACCOUNTS - existing_count)

new_accounts = []
for i in range(to_create):
    acc_id = start_id + i
    name = f"{random.choice(first_names)} {random.choice(last_names)}"
    avg_amount = round(random.uniform(200, 2000), 2)
    balance = round(random.uniform(5000, 100000), 2)
    location = random.choice(cities)

    # ~30% brand-new accounts (last 2 days), the rest older (up to 2 years)
    if random.random() < 0.3:
        created_at = now - timedelta(hours=random.randint(1, 48))
    else:
        created_at = now - timedelta(days=random.randint(60, 730))

    new_accounts.append((acc_id, name, balance, avg_amount, created_at, location))

if new_accounts:
    cursor.executemany(
        "INSERT INTO accounts (account_id, customer_name, balance, avg_transaction_amount, created_at, location) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        new_accounts,
    )
    con.commit()
print(f"Accounts: {existing_count} existing, {len(new_accounts)} newly created.")

cursor.execute("SELECT account_id, avg_transaction_amount, location, created_at FROM accounts")
all_accounts = cursor.fetchall()
account_ids = [a[0] for a in all_accounts]
account_lookup = {
    a[0]: {
        "avg": float(a[1]) if a[1] is not None else 0.0,
        "location": a[2],
        "created_at": a[3],
    }
    for a in all_accounts
}


def random_receiver(exclude_id):
    return random.choice([a for a in account_ids if a != exclude_id])


# ---------------------------------------------------------------------------
# Timestamp helpers: a transaction must fall AFTER the account was created and
# NOT in the future.
# ---------------------------------------------------------------------------
def window_start(acc):
    return max(acc["created_at"] + timedelta(minutes=5), now - timedelta(days=DAYS_BACK))


def pick_timestamp(acc, hour):
    """Random time on a random recent day at the wanted hour, inside the account's
    valid window. Returns None if no valid time is found (caller picks another sender)."""
    start = window_start(acc)
    for _ in range(30):
        candidate = now - timedelta(days=random.randint(0, DAYS_BACK))
        candidate = candidate.replace(
            hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59)
        )
        if start <= candidate <= now:
            return candidate
    return None


# ---------------------------------------------------------------------------
# 2. Normal / fraud / edge-case transactions.
# ---------------------------------------------------------------------------
records = []
attempts = 0

while len(records) < NUM_TRANSACTIONS and attempts < NUM_TRANSACTIONS * 20:
    attempts += 1
    sender_id = random.choice(account_ids)
    receiver_id = random_receiver(sender_id)
    acc = account_lookup[sender_id]
    home_location = acc["location"]

    roll = random.random()

    if roll < 0.80:
        # --- Normal transaction (80%) ---
        amount = round(random.uniform(20, acc["avg"] * 2 if acc["avg"] > 0 else 500), 2)
        hour = random.randint(7, 22)
        location = home_location
        is_fraud = 0

    elif roll < 0.95:
        # --- Obvious fraud (15%): big amount, night hours, different city ---
        amount = round(random.uniform(8000, 60000), 2)
        hour = random.choice(list(range(0, 6)) + [23])
        location = random.choice([c for c in cities if c != home_location])
        is_fraud = 1

    elif roll < 0.975:
        # --- Edge case: looks risky but is legit (2.5%) --- e.g. rent, tuition
        amount = round(random.uniform(9000, 15000), 2)
        hour = random.choice([22, 23, 6])
        location = home_location
        is_fraud = 0

    else:
        # --- Edge case: stealth fraud (2.5%) ---
        # Small amount, normal hour, home city: looks identical to a normal
        # transaction on these features, so no detector can reliably catch it.
        amount = round(random.uniform(500, 2000), 2)
        hour = random.randint(9, 18)
        location = home_location
        is_fraud = 1

    timestamp = pick_timestamp(acc, hour)
    if timestamp is None:
        continue  # account too new for this hour; try another sender

    records.append((sender_id, receiver_id, amount, timestamp, location, "pending", is_fraud))

# ---------------------------------------------------------------------------
# 3. Rapid-fire bursts (3-5 transactions within about a minute, same account).
#    Most are fraud, but some are legit (someone paying several bills at once).
# ---------------------------------------------------------------------------
bursts_made = 0
tries = 0
while bursts_made < NUM_BURSTS and tries < 500:
    tries += 1
    sender_id = random.choice(account_ids)
    receiver_id = random_receiver(sender_id)
    acc = account_lookup[sender_id]

    start = window_start(acc)
    latest = now - timedelta(minutes=10)
    if start >= latest:
        continue  # account too new

    base_time = start + timedelta(seconds=random.randint(0, int((latest - start).total_seconds())))
    burst_is_fraud = 1 if random.random() < 0.7 else 0
    burst_size = random.randint(3, 5)

    for j in range(burst_size):
        amount = round(random.uniform(500, 5000), 2)
        ts = base_time + timedelta(seconds=j * random.randint(5, 20))
        records.append((sender_id, receiver_id, amount, ts, acc["location"], "pending", burst_is_fraud))
    bursts_made += 1

# Insert in time order so transaction_id increases with time (like a real system).
records.sort(key=lambda r: r[3])

query = (
    "INSERT INTO transactions (sender_id, receiver_id, amount, timestamp, location, status, is_fraud) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s)"
)
cursor.executemany(query, records)
con.commit()

fraud_count = sum(r[6] for r in records)
print(f"Inserted {len(records)} transactions "
      f"({fraud_count} labeled fraud, {len(records) - fraud_count} labeled legit), "
      f"including {bursts_made} bursts.")

# ---------------------------------------------------------------------------
# 4. Self-check: no transaction before its account existed, none in the future.
# ---------------------------------------------------------------------------
cursor.execute(
    """
    SELECT COUNT(*) FROM transactions t
    JOIN accounts a ON t.sender_id = a.account_id
    WHERE t.timestamp < a.created_at
    """
)
before_account = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM transactions WHERE timestamp > %s", (now,))
in_future = cursor.fetchone()[0]

print(f"Transactions before account creation: {before_account} -> {'OK' if before_account == 0 else 'PROBLEM'}")
print(f"Transactions in the future:           {in_future} -> {'OK' if in_future == 0 else 'PROBLEM'}")
print("Done.")

cursor.close()
con.close()