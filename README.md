# 🛡️ Real-Time Financial Fraud Detection & Risk Scoring System

A real-time financial fraud monitoring system and web dashboard built to evaluate banking transactions using relational SQL queries, heuristic rules, and geographic velocity checks.

## 🚀 Features
* **Real-Time Risk Scoring:** Evaluates transactions dynamically based on amount limits, time windows, and spending anomalies.
* **Geospatial Velocity Analysis:** Flags impossible travel scenarios (e.g., transactions from Pune and Mumbai within minutes).
* **MySQL Integration:** Uses relational joins to compare incoming transactions against historical user behavior.
* **Fintech Web Dashboard:** Dark-mode UI built with Tailwind CSS displaying live status (`APPROVED`, `FLAGGED`, `BLOCKED`).

---

## 🛠️ Tech Stack
* **Backend:** Python, Flask
* **Database:** MySQL
* **Frontend:** HTML5, Tailwind CSS, Jinja Templates

---

## ⚙️ How to Run Locally

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/harshada-chavan15/Fraud-detection-system.git](https://github.com/harshada-chavan15/Fraud-detection-system.git)
   cd Fraud-detection-system
Install dependencies:

Bash
pip install flask mysql-connector-python
Set up the database:

Create a MySQL database named bank_system and set up your tables (accounts and transactions).

Run the application:

Bash
python app.py
Open in your browser:
Go to http://127.0.0.1:5000




Once you paste that whole thing into GitHub and click **Commit changes**, your README

## 🖼️ Dashboard Preview
<img width="1881" height="883" alt="image" src="https://github.com/user-attachments/assets/98dba944-cd55-47c6-8fda-bb613419329f" />

