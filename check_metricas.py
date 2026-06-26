import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')
conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
cur = conn.cursor()
cur.execute("""
    SELECT DISTINCT metrica FROM paneles 
    WHERE vista = 'Plan de Acción' 
    ORDER BY metrica
""")
print("Métricas en tabla paneles (Plan de Acción):")
for row in cur.fetchall():
    print(f"  - {row[0]}")
cur.close()
conn.close()
