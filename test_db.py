import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()
url = os.getenv("DATABASE_URL")
print(f"Usando: {url[:50]}...")

try:
    conn = psycopg2.connect(url)
    print("✅ CONEXIÓN EXITOSA")
    conn.close()
except Exception as e:
    print(f"❌ ERROR: {e}")
