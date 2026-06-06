import mysql.connector
import heapq
from datetime import datetime

con = mysql.connector.connect(
    host="localhost",
    user="root",
    password="root",
    database="bank_system"
)

cursor = con.cursor()

cursor.execute("""
    SELECT 
        t.transaction_id,
        t.sender_id,
        t.amount,
        t.timestamp,
        t.location,
        a.customer_name,
        a.avg_transaction_amount,
        a.created_at
    FROM transactions t
    JOIN accounts a ON t.sender_id = a.account_id
    WHERE t.status = 'pending'
 """
)

rows = cursor.fetchall()
print(f"Fetched {len(rows)} pending transactions")

def calculate_risk(row):
    risk=0

    if row[2]>=10000:
        risk=risk+3

    if row[3].hour>22 or row[3].hour<6:
        risk=risk+1

    if row[6] and row[2]>(3*row[6]):
        risk=risk+3

    if (datetime.now()-row[7]).total_seconds()<172800:
         risk=risk+2
    
    return risk
