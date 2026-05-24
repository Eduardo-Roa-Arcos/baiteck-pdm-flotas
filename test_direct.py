import psycopg2

try:
    conn = psycopg2.connect(
        host="db.kzwirmouuaazqblsbbjf.supabase.co",
        port=5432,
        database="postgres",
        user="postgres",
        password="Baiteck.2026"
    )
    cursor = conn.cursor()
    cursor.execute("SELECT version();")
    print("✅ Conexión directa OK:", cursor.fetchone())
    cursor.close()
    conn.close()
except Exception as e:
    print("❌ Error:", e)
