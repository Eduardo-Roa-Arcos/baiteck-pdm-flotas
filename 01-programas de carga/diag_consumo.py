#!/usr/bin/env python3
"""
Diagnóstico: Verificar por qué no hay consumo proyectado
"""

import sys
sys.path.insert(0, '/mnt/project')

import pandas as pd
from sqlalchemy import text
from src.db import engine

print("=" * 80)
print("DIAGNÓSTICO: Consumo Proyectado P1/P2")
print("=" * 80)

# 1. ¿Hay P1/P2?
print("\n1️⃣  ¿Hay activos con P1/P2?")
query = text("""
    SELECT prioridad, COUNT(*) as count
    FROM scoring_resultados
    GROUP BY prioridad
    ORDER BY prioridad
""")
with engine.connect() as conn:
    df = pd.read_sql(query, conn)
print(df.to_string(index=False))

# 2. ¿Tienen sistema_en_riesgo?
print("\n2️⃣  P1/P2 con sistema_en_riesgo:")
query = text("""
    SELECT 
        prioridad,
        COUNT(*) as total,
        COUNT(CASE WHEN sistema_en_riesgo IS NOT NULL THEN 1 END) as con_sistema,
        COUNT(CASE WHEN sistema_en_riesgo IS NULL THEN 1 END) as sin_sistema
    FROM scoring_resultados
    WHERE prioridad IN ('P1', 'P2')
    GROUP BY prioridad
""")
with engine.connect() as conn:
    df = pd.read_sql(query, conn)
print(df.to_string(index=False))

# 3. ¿Qué sistemas hay en P1/P2?
print("\n3️⃣  Sistemas en P1/P2:")
query = text("""
    SELECT DISTINCT sistema_en_riesgo
    FROM scoring_resultados
    WHERE prioridad IN ('P1', 'P2')
    ORDER BY sistema_en_riesgo
""")
with engine.connect() as conn:
    df = pd.read_sql(query, conn)
print(df.to_string(index=False))

# 4. Verificar marca/modelo de P1/P2
print("\n4️⃣  Marca/Modelo en P1/P2:")
query = text("""
    SELECT 
        a.marca, a.modelo, COUNT(*) as count
    FROM scoring_resultados sr
    JOIN activos a ON sr.activo_id = a.activo_id
    WHERE sr.prioridad IN ('P1', 'P2')
    GROUP BY a.marca, a.modelo
    ORDER BY count DESC
    LIMIT 10
""")
with engine.connect() as conn:
    df = pd.read_sql(query, conn)
print(df.to_string(index=False))

# 5. ¿Qué marcas/modelos/sistemas están en consumo_sistema_modelo?
print("\n5️⃣  Primeros 20 registros en consumo_sistema_modelo:")
query = text("""
    SELECT marca, modelo, sistema, COUNT(*) as num_skus
    FROM consumo_sistema_modelo
    GROUP BY marca, modelo, sistema
    LIMIT 20
""")
with engine.connect() as conn:
    df = pd.read_sql(query, conn)
print(df.to_string(index=False))

# 6. ¿Hay match entre P1/P2 y consumo_sistema_modelo?
print("\n6️⃣  Verificar match P1/P2 con consumo_sistema_modelo:")
query = text("""
    SELECT 
        a.marca, a.modelo, sr.sistema_en_riesgo,
        COUNT(DISTINCT sr.activo_id) as num_activos,
        COUNT(DISTINCT csm.sku) as num_skus_posibles
    FROM scoring_resultados sr
    JOIN activos a ON sr.activo_id = a.activo_id
    LEFT JOIN consumo_sistema_modelo csm 
        ON a.marca = csm.marca 
        AND a.modelo = csm.modelo 
        AND sr.sistema_en_riesgo = csm.sistema
    WHERE sr.prioridad IN ('P1', 'P2')
    GROUP BY a.marca, a.modelo, sr.sistema_en_riesgo
""")
with engine.connect() as conn:
    df = pd.read_sql(query, conn)
if len(df) > 0:
    print(df.to_string(index=False))
else:
    print("❌ No hay ningún match")

print("\n" + "=" * 80)
