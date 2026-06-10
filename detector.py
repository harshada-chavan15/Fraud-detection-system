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
        a.created_at,
        prev.location    AS prev_location,
        prev.timestamp   AS prev_timestamp
    FROM transactions t
    JOIN accounts a ON t.sender_id = a.account_id
    
    LEFT JOIN transactions prev 
               ON prev.sender_id = t.sender_id 
               and prev.timestamp < t.timestamp
               and prev.timestamp=(SELECT MAX(TIMESTAMP) 
               FROM TRANSACTIONS  
               WHERE sender_id = t.sender_id 
               and timestamp < t.timestamp
               )
    WHERE t.status = 'pending';
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

    if row[8]:
        cities={
            "Mumbai-Pune":150,
            "Bangalore-Surat":1250,
            "Bangalore-Mumbai":980,
            "Bangalore-Pune":840,
            "Mumbai-Surat":280,
            "Surat-Pune":420
            }
        pair=row[4]+"-"+row[8]
        reversed_pair=row[8]+"-"+row[4]

        distance=cities.get(pair) or cities.get(reversed_pair)


        time_diff=((row[3]-row[9]).total_seconds())/60
        if distance>500 and time_diff<60  :
           risk=risk+5
    
    

    cursor.execute("""SELECT COUNT(*) from transactions 
         where sender_id=%s 
         and timestamp>=NOW()-INTERVAL 1 MINUTE""",(row[1],))

    count=cursor.fetchone()[0]


    if count>2:
         risk=risk+4


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










    
 