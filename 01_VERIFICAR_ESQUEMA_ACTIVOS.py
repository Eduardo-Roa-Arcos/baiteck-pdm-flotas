#!/usr/bin/env python3
import os
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, inspect

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True, echo=False)

print("=" * 80)
print("ESTRUCTURA EXACTA DE LA TABLA: activos")
print("=" * 80)

inspector = inspect(engine)
columns = inspector.get_columns("activos")

print("\nCOLUMNAS:")
for col in columns:
    nullable = "NULL" if col["nullable"] else "NOT NULL"
    print(f"  • {col['name']:30} {str(col['type']):20} {nullable}")

print("\nSAMPLE DE 3 REGISTROS:")
with engine.connect() as conn:
    from sqlalchemy import text
    result = conn.execute(text("SELECT * FROM activos LIMIT 3"))
    
    for row_idx, row in enumerate(result.fetchall(), 1):
        print(f"\n[Registro {row_idx}]")
        for col, val in zip(result.keys(), row):
            print(f"  {col:30} = {val}")

print("\n" + "=" * 80)
