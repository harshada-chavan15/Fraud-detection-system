from flask import Flask, render_template, request, redirect, url_for
import mysql.connector
from datetime import datetime

app = Flask(__name__)

def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="root",
        database="bank_system"
    )

def calculate_risk(row, cursor):
    risk = 0
  
    # row index mapping based on query below:
    # 0: transaction_id, 1: sender_id, 2: amount, 3: timestamp, 4: location, 
    # 5: customer_name, 6: avg_transaction_amount, 7: created_at, 
    # 8: prev_location, 9: prev_timestamp, 10: status

    if row[2] >= 10000:
        risk = risk + 3

    if row[3].hour > 22 or row[3].hour < 6:
        risk = risk + 2

    if row[6] and row[2] > (3 * row[6]):
        risk = risk + 3

    if (datetime.now() - row[7]).total_seconds() < 172800:
        risk = risk + 2

    # Location & Velocity Check (e.g., Pune to Mumbai in < 60 mins)
    if row[8]:
        cities = {
            "Mumbai-Pune": 150,
            "Bangalore-Surat": 1250,
            "Bangalore-Mumbai": 980,
            "Bangalore-Pune": 840,
            "Mumbai-Surat": 280,
            "Surat-Pune": 420
        }
        pair = str(row[4]) + "-" + str(row[8])
        reversed_pair = str(row[8]) + "-" + str(row[4])

        distance = cities.get(pair) or cities.get(reversed_pair)
        if distance and row[9]:
            time_diff = ((row[3] - row[9]).total_seconds()) / 60
            if distance > 500 and time_diff < 60:
                risk = risk + 5
            elif distance > 100 and time_diff < 15: # Added tighter check for Pune/Mumbai speed
                risk = risk + 5
    
    cursor.execute("""
        SELECT COUNT(*) FROM transactions 
        WHERE sender_id = %s 
        AND timestamp >= NOW() - INTERVAL 1 MINUTE
    """, (row[1],))

    count = cursor.fetchone()[0]
    if count > 2:
        risk = risk + 4

    return risk

@app.route('/', methods=['GET', 'POST'])
def home():
    con = get_db()
    cursor = con.cursor()
    
    if request.method == 'POST':
        sender_id = int(request.form['sender_id'])
        receiver_id = int(request.form['receiver_id'])
        amount = float(request.form['amount'])
        location = request.form['location']
        
        # 1. Insert new transaction as pending
        cursor.execute("""
            INSERT INTO transactions (sender_id, receiver_id, amount, location, status, timestamp) 
            VALUES (%s, %s, %s, %s, 'pending', NOW())
        """, (sender_id, receiver_id, amount, location))
        con.commit()

        # 2. Immediately evaluate ALL pending transactions
        cursor.execute("""
            SELECT 
                t.transaction_id,
                t.sender_id,
                t.amount,
                t.timestamp,
                t.location,
                a.customer_name,
                a.avg_transaction_amount,
                a.created_at,
                prev.location AS prev_location,
                prev.timestamp AS prev_timestamp,
                t.status
            FROM transactions t
            JOIN accounts a ON t.sender_id = a.account_id
            LEFT JOIN transactions prev
                ON prev.sender_id = t.sender_id
                AND prev.timestamp < t.timestamp
                AND prev.transaction_id != t.transaction_id
                AND prev.timestamp = (
                    SELECT MAX(timestamp) FROM transactions
                    WHERE sender_id = t.sender_id
                    AND timestamp < t.timestamp
                )
            WHERE t.status = 'pending'
        """)
        pending_rows = cursor.fetchall()

        for row in pending_rows:
            risk = calculate_risk(row, cursor)
            
            if risk >= 6:
                action = "BLOCKED"
            elif risk >= 3:
                action = "FLAGGED"
            else:
                action = "APPROVED"
            
            up_cursor = con.cursor()
            up_cursor.execute("""
                UPDATE transactions 
                SET status = %s, risk_score = %s 
                WHERE transaction_id = %s
            """, (action, risk, row[0]))
            con.commit()
            up_cursor.close()

    # Fetch recent transactions to display on dashboard table
    cursor.execute("""
        SELECT transaction_id, sender_id, receiver_id, amount, location, risk_score, status 
        FROM transactions 
        ORDER BY timestamp DESC 
        LIMIT 10
    """)
    db_rows = cursor.fetchall()
    
    results = []
    for r in db_rows:
        results.append({
            'id': r[0],
            'sender_id': r[1],
            'receiver_id': r[2],
            'amount': float(r[3]),
            'location': r[4],
            'risk_score': r[5] if r[5] is not None else 0,
            'status': r[6]
        })
    
    cursor.close()
    con.close()
    
    return render_template('index.html', transactions=results)

if __name__ == "__main__":
    app.run(debug=True)