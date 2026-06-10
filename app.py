from flask import Flask, render_template, request, jsonify
import mysql.connector
import heapq
from datetime import datetime

app = Flask(__name__)

def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="root",
        database="bank_system"
    )


@app.route('/')
def home():
    transactions = [
        {'id': 1, 'name': 'Arshita', 'amount': 120},
        {'id': 4, 'name': 'Tanish',  'amount': 50000}
    ]
    return render_template('index.html', transactions=transactions)

def test():
    return "I understand routes!"

if __name__ == "__main__":
    app.run(debug=True)