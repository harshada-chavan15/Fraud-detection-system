"""
risk_engine.py

The rule-based scoring logic, in ONE place. Both detector.py (batch scoring) and
app.py (live dashboard) import from here, so the rules can never drift apart.

score_transaction() is pure logic: it takes plain dicts and never touches the
database, so it is easy to unit test.

    score, reasons = score_transaction(txn, prev, recent_count)
    action = decide(score)      # "BLOCKED" / "FLAGGED" / "APPROVED"
"""

# ---------------------------------------------------------------------------
# Thresholds (change these to tune the engine)
# ---------------------------------------------------------------------------
HIGH_AMOUNT = 10000          # amount >= this is "high"
AMOUNT_MULTIPLIER = 3        # amount > 3x the account's average
NIGHT_AFTER_HOUR = 22        # hour > 22 (i.e. 23:00 onwards)...
NIGHT_BEFORE_HOUR = 6        # ...or hour < 6
NEW_ACCOUNT_HOURS = 48       # account younger than this at transaction time
VELOCITY_LIMIT = 2           # more than this many txns in 1 minute = velocity

BLOCK_AT = 6                 # score >= 6  -> BLOCKED
FLAG_AT = 3                  # score >= 3  -> FLAGGED, otherwise APPROVED

# Approximate road distances between cities, in km
CITY_DISTANCES = {
    "Mumbai-Pune": 150,
    "Bangalore-Surat": 1250,
    "Bangalore-Mumbai": 980,
    "Bangalore-Pune": 840,
    "Mumbai-Surat": 280,
    "Surat-Pune": 420,
}


def distance_between(city_a, city_b):
    """Distance in km. Returns 0 for the same city OR an unknown pair, so the
    travel rule is simply skipped instead of crashing."""
    if city_a == city_b:
        return 0
    return (CITY_DISTANCES.get(f"{city_a}-{city_b}")
            or CITY_DISTANCES.get(f"{city_b}-{city_a}")
            or 0)


def score_transaction(txn, prev, recent_count):
    """
    txn: dict with
        amount, timestamp (datetime), location,
        avg_amount (account's average, may be None/0),
        account_created_at (datetime)
    prev: dict with location, timestamp for the sender's previous transaction,
          or None if this is their first
    recent_count: how many transactions this sender made in the 1 minute up to
                  txn["timestamp"] (includes this transaction itself)

    Returns (score, reasons) where reasons is a list of human-readable strings.
    """
    score = 0
    reasons = []

    amount = float(txn["amount"])
    ts = txn["timestamp"]
    avg = float(txn["avg_amount"]) if txn.get("avg_amount") else 0.0

    # 1. High amount
    if amount >= HIGH_AMOUNT:
        score += 3
        reasons.append("high amount")

    # 2. Night-time
    if ts.hour > NIGHT_AFTER_HOUR or ts.hour < NIGHT_BEFORE_HOUR:
        score += 2
        reasons.append("night-time transaction")

    # 3. Far above this account's usual amount
    if avg and amount > AMOUNT_MULTIPLIER * avg:
        score += 3
        reasons.append(f"amount > {AMOUNT_MULTIPLIER}x account average")

    # 4. Brand-new account (age measured at the transaction's own time)
    age_seconds = (ts - txn["account_created_at"]).total_seconds()
    if age_seconds < NEW_ACCOUNT_HOURS * 3600:
        score += 2
        reasons.append(f"new account (<{NEW_ACCOUNT_HOURS}h old)")

    # 5. Impossible travel (only if there is a previous txn and a known distance)
    if prev and prev.get("location") and prev.get("timestamp"):
        km = distance_between(txn["location"], prev["location"])
        if km > 0:
            minutes = (ts - prev["timestamp"]).total_seconds() / 60
            if (km > 500 and minutes < 60) or (km > 100 and minutes < 15):
                score += 5
                reasons.append(f"impossible travel: {km} km in {minutes:.0f} min")

    # 6. Velocity: many transactions within a minute
    if recent_count > VELOCITY_LIMIT:
        score += 4
        reasons.append(f"velocity: {recent_count} transactions in 1 minute")

    return score, reasons


def decide(score):
    if score >= BLOCK_AT:
        return "BLOCKED"
    if score >= FLAG_AT:
        return "FLAGGED"
    return "APPROVED"


# ---------------------------------------------------------------------------
# Database helper (takes a cursor; the scoring above stays DB-free)
# ---------------------------------------------------------------------------
def count_recent(cursor, sender_id, ts):
    """Transactions by this sender in the 1 minute ending at ts (includes ts itself).
    Uses the transaction's OWN time, not NOW(), so it also works on old data."""
    cursor.execute(
        """
        SELECT COUNT(*) FROM transactions
        WHERE sender_id = %s
          AND timestamp BETWEEN %s - INTERVAL 1 MINUTE AND %s
        """,
        (sender_id, ts, ts),
    )
    return cursor.fetchone()[0]
