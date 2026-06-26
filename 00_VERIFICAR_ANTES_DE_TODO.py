#!/usr/bin/env python3
"""
VERIFICACIÓN PREVIA - Estructura exacta de taxonomia_fallas
NO HAGAS QUERIES HASTA VERIFICAR ESTO
"""

import os
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, inspect, text

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL no está definido")
    exit(1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, echo=False)

print("=" * 80)
print("1️⃣ ESTRUCTURA DE TABLA: taxonomia_fallas")
print("=" * 80)

inspector = inspect(engine)
columns = inspector.get_columns("taxonomia_fallas")

print("\nCOLUMNAS DISPONIBLES:")
for col in columns:
    nullable = "NULL" if col["nullable"] else "NOT NULL"
    print(f"  • {col['name']:30} {str(col['type']):20} {nullable}")

print("\n" + "=" * 80)
print("2️⃣ SAMPLE DE DATOS (primer registro)")
print("=" * 80)

with engine.connect() as conn:
    result = conn.execute(text("SELECT * FROM taxonomia_fallas LIMIT 1"))
    row = result.fetchone()
    
    if row:
        cols = result.keys()
        for col, val in zip(cols, row):
            print(f"  {col:30} = {val}")
    else:
        print("  (tabla vacía)")

print("\n" + "=" * 80)
print("3️⃣ BÚSQUEDA: ¿Qué taxonomías contienen 'freno'?")
print("=" * 80)

with engine.connect() as conn:
    # Query genérico que busca 'freno' en cualquier columna de texto
    result = conn.execute(
        text("""
            SELECT * FROM taxonomia_fallas 
            WHERE LOWER(CAST(sistema AS TEXT)) LIKE '%freno%'
            OR LOWER(CAST(componente AS TEXT)) LIKE '%freno%'
            LIMIT 5
        """)
    )
    
    rows = result.fetchall()
    if not rows:
        print("  ❌ No se encontraron registros con 'freno'")
    else:
        print(f"  ✅ Encontrados {len(rows)} registros:")
        for row in rows:
            cols = result.keys()
            print("\n  ---")
            for col, val in zip(cols, row):
                print(f"    {col:30} = {val}")

print("\n" + "=" * 80)
