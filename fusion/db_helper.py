import mysql.connector

def get_conn():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="surbhi",    # ← change this
        database="crowd_ai"
    )