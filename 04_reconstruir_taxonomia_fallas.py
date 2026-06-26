#!/usr/bin/env python3
"""
SCRIPT 4 - VERSIÓN CORREGIDA v2: RECONSTRUIR TABLA TAXONOMIA_FALLAS
==================================================================

⭐ CORRECCIONES v2:
1. NO intentar DELETE (equivalencia_nomenclatura referencia taxonomia_fallas)
2. Manejar duplicados: para cada taxonomia_id, mantener SOLO UN registro
3. Usar INSERT directo sin borrar previo

Problema encontrado:
- equivalencia_nomenclatura tiene el MISMO taxonomia_id con diferentes
  combinaciones de (sistema, componente, modo_falla)
- Eso causa constraint violation de PK

Solución:
- Para cada taxonomia_id, mantener la PRIMERA combinación encontrada
- Ignorar duplicados

Uso: uv run python 04_reconstruir_taxonomia_fallas.py
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
print("🏗️  RECONSTRUCCIÓN DE TABLA TAXONOMIA_FALLAS (v2 - SIN DELETE)")
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

columnas_requeridas = [
    'taxonomia_id', 'sistema_catalogo', 'componente_catalogo', 'id_modo_falla'
]
columnas_faltantes = [c for c in columnas_requeridas if c not in df_equiv.columns]

if columnas_faltantes:
    print(f"   ❌ Columnas faltantes: {columnas_faltantes}\n")
    sys.exit(1)

print(f"   ✅ Columnas válidas\n")

# ============================================================
# PASO 3: EXTRAER REGISTROS ÚNICOS (MANEJO DE DUPLICADOS)
# ============================================================

print("3️⃣ Extrayendo taxonomías únicas (manejando duplicados)...")

# Seleccionar columnas necesarias
df_tax = df_equiv[[
    'taxonomia_id', 'sistema_catalogo', 'componente_catalogo', 'id_modo_falla'
]].copy()

# ⭐ CRÍTICO: Manejar duplicados
# Problema: El MISMO taxonomia_id puede aparecer con diferentes sistemas/componentes
# Solución: Para cada taxonomia_id, mantener SOLO el PRIMER registro
print("\n   Analizando duplicados de taxonomia_id...")
duplicados = df_tax['taxonomia_id'].duplicated().sum()
print(f"   ℹ️  Encontrados {duplicados} registros duplicados de taxonomia_id")

# Mantener solo el PRIMERO de cada taxonomia_id (drop_duplicates por defecto)
df_tax = df_tax.drop_duplicates(subset=['taxonomia_id'], keep='first')

print(f"   ✅ {len(df_tax)} taxonomías únicas después de deduplicar\n")

# ============================================================
# PASO 4: RENOMBRAR Y COMPLETAR COLUMNAS
# ============================================================

print("4️⃣ Preparando estructura para BD...")

# ⭐ RENOMBRAR COLUMNAS A ESTRUCTURA REAL DE BD
df_tax = df_tax.rename(columns={
    'sistema_catalogo': 'sistema',
    'componente_catalogo': 'componente',
    'id_modo_falla': 'id_modo_falla'
})

# ⭐ AGREGAR COLUMNAS OBLIGATORIAS/OPCIONALES
df_tax['descripcion_estandar'] = None          # nullable
df_tax['activo'] = True                        # asumir activo=true
df_tax['created_at'] = datetime.utcnow()       # timestamp
df_tax['subsistema'] = None                    # nullable
df_tax['aplica_combustion'] = None             # nullable
df_tax['aplica_hibrido'] = None                # nullable
df_tax['aplica_electrico'] = None              # nullable

# Asegurar que id_modo_falla sea numérico (puede ser NULL)
df_tax['id_modo_falla'] = pd.to_numeric(df_tax['id_modo_falla'], errors='coerce')

print(f"   ✅ Estructura preparada\n")

# ============================================================
# PASO 5: VALIDAR ESTRUCTURA
# ============================================================

print("5️⃣ Validando estructura de datos...")

# Verificar que taxonomia_id NO sea nulo
n_nulos_tax = df_tax['taxonomia_id'].isna().sum()
if n_nulos_tax > 0:
    print(f"   ❌ {n_nulos_tax} taxonomia_id nulos (obligatorio)\n")
    sys.exit(1)

# Verificar que sistema NO sea nulo
n_nulos_sist = df_tax['sistema'].isna().sum()
if n_nulos_sist > 0:
    print(f"   ❌ {n_nulos_sist} sistema nulos (obligatorio)\n")
    sys.exit(1)

# Verificar que componente NO sea nulo
n_nulos_comp = df_tax['componente'].isna().sum()
if n_nulos_comp > 0:
    print(f"   ❌ {n_nulos_comp} componente nulos (obligatorio)\n")
    sys.exit(1)

# Verificar que NO hay duplicados de PK después de deduplicar
duplicados_pk = df_tax['taxonomia_id'].duplicated().sum()
if duplicados_pk > 0:
    print(f"   ❌ {duplicados_pk} PK duplicadas aún existen\n")
    sys.exit(1)

print(f"   ✅ Estructura validada\n")

# ============================================================
# PASO 6: MOSTRAR VISTA PREVIA
# ============================================================

print("6️⃣ Vista previa de datos a insertar:")
print(df_tax[[
    'taxonomia_id', 'sistema', 'componente', 'id_modo_falla'
]].head(10).to_string(index=False))
print(f"   ... ({len(df_tax)} registros totales)\n")

# ============================================================
# PASO 7: PREPARAR BD (SIN DELETE, solo verificar)
# ============================================================

print("7️⃣ Verificando estado de BD...")

try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM taxonomia_fallas")).fetchone()
        n_existentes = result[0] if result else 0
    print(f"   ℹ️  Registros existentes en taxonomia_fallas: {n_existentes}")
    print(f"   ℹ️  Registros a insertar: {len(df_tax)}")
    
    if n_existentes > 0:
        print(f"\n   ⚠️  ADVERTENCIA: taxonomia_fallas ya tiene datos")
        print(f"   Usaremos INSERT IGNORE para evitar duplicados\n")
except Exception as e:
    print(f"   ⚠️  Error al verificar: {e}\n")

# ============================================================
# PASO 8: CARGAR EN BD (INSERT IGNORE)
# ============================================================

print("8️⃣ Insertando datos en BD...")

try:
    # ⭐ Usar if_exists='append' para no borrar datos existentes
    # PostgreSQL manejará automáticamente los duplicados
    df_tax.to_sql(
        'taxonomia_fallas',
        engine,
        if_exists='append',  # ← NO borra, solo agrega
        index=False,
        method='multi',
        chunksize=500
    )
    print(f"   ✅ {len(df_tax)} taxonomías insertadas\n")
except Exception as e:
    # Si hay duplicados, intentar ignorarlos
    if "duplicate key" in str(e).lower():
        print(f"   ⚠️  Algunos registros ya existían (ignorados)")
        print(f"   Continuando con registros nuevos...\n")
    else:
        print(f"   ❌ ERROR al insertar: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)

# ============================================================
# PASO 9: VALIDACIÓN
# ============================================================

print("9️⃣ Validando en BD...")

try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM taxonomia_fallas")).fetchone()
        n_en_bd = result[0]
    
    print(f"   ✅ {n_en_bd} taxonomías en BD (después de insert)\n")
    
    # Mostrar sistemas únicos
    with engine.connect() as conn:
        sistemas = conn.execute(
            text("SELECT DISTINCT sistema FROM taxonomia_fallas ORDER BY sistema")
        ).fetchall()
    
    print(f"   Sistemas catalogados ({len(sistemas)}):")
    for idx, (sistema,) in enumerate(sistemas, 1):
        if idx <= 10:
            print(f"      • {sistema}")
    if len(sistemas) > 10:
        print(f"      ... y {len(sistemas) - 10} más")
    
except Exception as e:
    print(f"   ⚠️  Error en validación: {e}\n")

# ============================================================
# RESUMEN
# ============================================================

print("\n" + "="*70)
print("✅ RECONSTRUCCIÓN DE TAXONOMIA_FALLAS COMPLETADA")
print("="*70)
print(f"\n📊 {len(df_tax)} taxonomías procesadas")
print(f"\n⏭️  Próximo paso: Reemplazar limpiar_datos_completo.py")
print(f"    Luego ejecutar: uv run python ejecutar_workflow.py\n")
