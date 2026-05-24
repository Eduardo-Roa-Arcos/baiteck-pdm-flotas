#!/usr/bin/env python3
import os
from dotenv import load_dotenv
import psycopg2
import pandas as pd
from datetime import datetime
from predictor import Predictor

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

print("=" * 60)
print("🔧 TEST SCORING COMPLETO")
print("=" * 60)

try:
    # 1. Cargar activos
    print("\n[1] Cargando activos...")
    conn = psycopg2.connect(DATABASE_URL)
    df_activos = pd.read_sql("SELECT activo_id FROM activos", conn)
    print(f"✅ {len(df_activos)} activos cargados")
    
    # 2. Cargar predictor
    print("\n[2] Cargando predictor...")
    p = Predictor()
    print("✅ Predictor cargado")
    
    # 3. Hacer predicciones
    print("\n[3] Haciendo predicciones...")
    resultados = []
    for activo_id in df_activos['activo_id'].values:
        try:
            result = p.predict(activo_id)
            resultados.append(result)
            print(f"   ✅ {activo_id}: prob={result['probabilidades']:.3f}")
        except Exception as e:
            print(f"   ❌ {activo_id}: {e}")
    
    print(f"\n✅ {len(resultados)} predicciones exitosas")
    
    # 4. Convertir a DataFrame
    print("\n[4] Creando DataFrame...")
    df_resultados = pd.DataFrame(resultados)
    df_resultados['fecha_scoring'] = datetime.now().date()
    print(f"✅ DataFrame creado: {df_resultados.shape}")
    print(df_resultados.head())
    
    # 5. Guardar en Supabase
    print("\n[5] Guardando en scoring_resultados...")
    df_resultados.to_sql('scoring_resultados', conn, if_exists='append', index=False)
    print("✅ Datos guardados")
    
    # 6. Verificar
    print("\n[6] Verificando...")
    df_check = pd.read_sql("SELECT COUNT(*) as total FROM scoring_resultados", conn)
    print(f"✅ Total registros en scoring_resultados: {int(df_check['total'].iloc[0])}")
    
    conn.close()

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
