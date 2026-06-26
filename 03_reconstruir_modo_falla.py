#!/usr/bin/env python3
"""
SCRIPT 3 - VERSIÓN CORREGIDA: RECONSTRUIR TABLA MODO_FALLA
===========================================================

⭐ CORRECCIONES:
1. Estructura correcta de modo_falla:
   - id_modo_falla (PK, smallint)
   - modo (TEXT, nombre del modo)
   - palabras_claves (TEXT, nullable)
   - created_at (timestamp, NOT NULL)

2. Orden correcto de truncado (respeta FK):
   - Primero borrar taxonomia_fallas (depende de modo_falla)
   - Luego borrar modo_falla (independiente)

Uso: uv run python 03_reconstruir_modo_falla.py
"""

import os
import sys
from pathlib import Path
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Cargar .env
env_path = Path(__file__).parent / ".env"
if not env_path.exists():
    raise RuntimeError(f"No se encontró .env en {Path(__file__).parent}")

load_dotenv(dotenv_path=env_path, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no está definida en .env")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

print("="*70)
print("🔧 RECONSTRUCCIÓN DE TABLA MODO_FALLA (VERSIÓN CORREGIDA)")
print("="*70 + "\n")

# ============================================================
# PASO 1: CARGAR EQUIVALENCIA_NOMENCLATURA
# ============================================================

print("1️⃣ Cargando equivalencia_nomenclatura.csv...")
try:
    df_equiv = pd.read_csv('data/raw/equivalencia_nomenclatura.csv')
    print(f"   ✅ {len(df_equiv)} equivalencias cargadas\n")
except FileNotFoundError:
    print(f"   ❌ ERROR: data/raw/equivalencia_nomenclatura.csv no encontrado\n")
    sys.exit(1)
except Exception as e:
    print(f"   ❌ ERROR: {e}\n")
    sys.exit(1)

# ============================================================
# PASO 2: VALIDAR COLUMNAS REQUERIDAS
# ============================================================

print("2️⃣ Validando columnas requeridas...")

columnas_requeridas = ['id_modo_falla', 'modo_catalogo']
columnas_faltantes = [c for c in columnas_requeridas if c not in df_equiv.columns]

if columnas_faltantes:
    print(f"   ❌ Columnas faltantes: {columnas_faltantes}\n")
    sys.exit(1)

print(f"   ✅ Columnas válidas\n")

# ============================================================
# PASO 3: EXTRAER PARES ÚNICOS Y PREPARAR PARA BD
# ============================================================

print("3️⃣ Extrayendo modos únicos...")

# Crear DataFrame con pares únicos de (id_modo_falla, modo_catalogo)
df_modos = df_equiv[['id_modo_falla', 'modo_catalogo']].drop_duplicates()

# ⭐ RENOMBRAR COLUMNAS A ESTRUCTURA REAL DE BD
df_modos = df_modos.rename(columns={
    'id_modo_falla': 'id_modo_falla',  # PK en BD
    'modo_catalogo': 'modo'             # Columna de nombre en BD
})

# ⭐ AGREGAR COLUMNAS OBLIGATORIAS
df_modos['created_at'] = datetime.utcnow()  # timestamp NOT NULL
df_modos['palabras_claves'] = None          # nullable, podría agregarse después

# Ordenar por id para mantener consistencia
df_modos = df_modos.sort_values('id_modo_falla').reset_index(drop=True)

print(f"   ✅ {len(df_modos)} modos únicos identificados\n")

# ============================================================
# PASO 4: MOSTRAR VISTA PREVIA
# ============================================================

print("4️⃣ Vista previa de datos a insertar:")
print(df_modos[['id_modo_falla', 'modo']].head(10).to_string(index=False))
print(f"   ... ({len(df_modos)} registros totales)\n")

# ============================================================
# PASO 5: TRUNCAR TABLAS (ORDEN INVERSO DE FK)
# ============================================================

print("5️⃣ Preparando tablas en BD (respetando FK)...")

try:
    with engine.connect() as conn:
        trans = conn.begin()
        
        # ⭐ PASO 5A: Primero borrar taxonomia_fallas (depende de modo_falla)
        try:
            conn.execute(text("DELETE FROM taxonomia_fallas CASCADE;"))
            print(f"   ✅ taxonomia_fallas vaciada (tenía referencias)")
        except Exception as e:
            if "does not exist" in str(e).lower():
                print(f"   ⚠️  taxonomia_fallas no existe (omitida)")
            else:
                print(f"   ⚠️  Error al vaciar taxonomia_fallas: {str(e)[:60]}")
        
        # ⭐ PASO 5B: Luego borrar modo_falla (ahora sin referencias)
        try:
            conn.execute(text("DELETE FROM modo_falla;"))
            print(f"   ✅ modo_falla vaciada")
        except Exception as e:
            if "does not exist" in str(e).lower():
                print(f"   ⚠️  modo_falla no existe (omitida)")
            else:
                raise
        
        trans.commit()
    print()
except Exception as e:
    print(f"   ❌ ERROR al preparar tablas: {e}\n")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================
# PASO 6: CARGAR EN BD
# ============================================================

print("6️⃣ Insertando datos en BD...")

try:
    # ⭐ Insertar con columnas en orden correcto
    df_modos.to_sql(
        'modo_falla',
        engine,
        if_exists='append',
        index=False,
        method='multi',
        chunksize=500
    )
    print(f"   ✅ {len(df_modos)} modos insertados\n")
except Exception as e:
    print(f"   ❌ ERROR al insertar: {e}\n")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================
# PASO 7: VALIDACIÓN
# ============================================================

print("7️⃣ Validando en BD...")

try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM modo_falla")).fetchone()
        n_en_bd = result[0]
    
    if n_en_bd == len(df_modos):
        print(f"   ✅ {n_en_bd} modos confirmados en BD\n")
    else:
        print(f"   ⚠️  Discrepancia: {len(df_modos)} en CSV vs {n_en_bd} en BD\n")
except Exception as e:
    print(f"   ⚠️  Error en validación: {e}\n")

# ============================================================
# RESUMEN
# ============================================================

print("="*70)
print("✅ RECONSTRUCCIÓN DE MODO_FALLA COMPLETADA")
print("="*70)
print(f"\n📊 {len(df_modos)} modos de falla reconstruidos")
print("\nModos identificados:")
for idx, (_, row) in enumerate(df_modos.iterrows(), 1):
    if idx <= 10:  # Mostrar solo primeros 10
        print(f"   • ID {row['id_modo_falla']:2d}: {row['modo']}")
if len(df_modos) > 10:
    print(f"   ... y {len(df_modos) - 10} más")
print(f"\n⏭️  Próximo paso: 04_reconstruir_taxonomia_fallas.py\n")
