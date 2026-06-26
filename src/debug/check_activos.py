import psycopg2, os, pandas as pd
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.getenv("DATABASE_URL"))

df = pd.read_sql("SELECT COUNT(*) as total FROM activos", conn)
print("Total activos:", int(df['total'].iloc[0]))

df = pd.read_sql("SELECT COUNT(*) as total FROM activos WHERE estado_actual = 'activo'", conn)
print("Con estado='activo':", int(df['total'].iloc[0]))

conn.close()
