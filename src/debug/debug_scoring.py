#!/usr/bin/env python3
import os, sys
from dotenv import load_dotenv
import psycopg2
import pandas as pd

load_dotenv()

print("=" * 60)
print("🔧 DEBUG SCORING")
print("=" * 60)

DATABASE_URL = os.getenv("DATABASE_URL")

print("\n[1] Verificando modelo entrenado...")
try:
    conn = psycopg2.connect(DATABASE_URL)
    df = pd.read_sql("SELECT COUNT(*) as cant FROM modelos_registro", conn)
    print(f"✅ Modelos registrados: {int(df['cant'].iloc[0])}")
    conn.close()
except Exception as e:
    print(f"❌ Error: {e}")

print("\n[2] Verificando archivo del modelo...")
if os.path.exists("models/modelo_xgb_v1.joblib"):
    print("✅ Archivo existe")
else:
    print("❌ No existe models/modelo_xgb_v1.joblib")

print("\n[3] Importando Predictor...")
try:
    from predictor import Predictor
    p = Predictor()
    print("✅ Predictor cargado")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
