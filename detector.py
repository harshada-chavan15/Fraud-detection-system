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
        risk=risk+2

    if row[6] and row[2]>(3*row[6]):
        risk=risk+3

    if (datetime.now()-row[7]).total_seconds()<172800:
         risk=risk+2
    
    return risk


heap=[]

for row in rows:
    risk=calculate_risk(row)
    heapq.heappush(heap,(-risk,row[0],row))


print("====FRAUD DETECTION REPORT====")

while heap :
    ngtv_risk,trscn_id,row=heapq.heappop(heap)
    real_risk=-1*ngtv_risk

    if real_risk>=6:
        action="BLOCKED"

    elif real_risk>=3 :
        action="FLAGGED"

    elif real_risk<3:
        action="APPROVED"

    print(trscn_id,row[5],row[2],real_risk,action)
    
 