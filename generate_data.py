import mysql.connector
from datetime import datetime, timedelta

con=mysql.connector.connect(
    host="localhost",
    user="root",
    password="root",
    database="bank_system"
)

cursor=con.cursor()

query="Insert into transactions (sender_id,receiver_id,amount,timestamp,location,status) values(%s,%s,%s,%s,%s,%s)"


records_to_insert=[
    (1,2,120.00,datetime.now() - timedelta(hours=2),'Mumbai','pending'),
    (3,1,620.00,datetime.now() - timedelta(days=1),'Pune','pending'),
    (4,2,466.00,datetime.now() - timedelta(minutes=26),'Surat','pending'),
    (3,2,50000.00,datetime.now(),'Surat','pending'),
    (3,2,20000.00,datetime.now()-timedelta(minutes=1),'Pune','pending'),
    (3,2,10000.00,datetime.now()-timedelta(minutes=2),'Bangalore','pending'),

]

cursor.executemany(query,records_to_insert)
con.commit()

print("Succesful!")

cursor.close()
con.close()


