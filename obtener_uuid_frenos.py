#!/usr/bin/env python3
"""
Buscar taxonomía_id para FRENOS
"""

import os
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL no está definido en .env")
    exit(1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, echo=False)

print("=" * 80)
print("🔍 BUSCANDO TAXONOMÍAS DE FRENOS")
print("=" * 80)

with engine.connect() as conn:
    result = conn.execute(
        text("""
            SELECT taxonomia_id, sistema, componente, modo_falla, descripcion_estandar
            FROM taxonomia_fallas
            WHERE activo = TRUE 
            AND LOWER(sistema) LIKE '%freno%'
            ORDER BY sistema, componente
        """)
    )
    
    frenos = result.fetchall()
    
    if not frenos:
        print("\n❌ No se encontraron taxonomías de FRENOS")
        print("\nBuscando todas las taxonomías disponibles:")
        result = conn.execute(
            text("""
                SELECT DISTINCT sistema 
                FROM taxonomia_fallas 
                WHERE activo = TRUE
                ORDER BY sistema
            """)
        )
        sistemas = result.fetchall()
        for (sistema,) in sistemas:
            print(f"   • {sistema}")
    else:
        print(f"\n✅ Encontradas {len(frenos)} taxonomías de FRENOS:\n")
        for taxonomia_id, sistema, componente, modo_falla, descripcion in frenos:
            print(f"   Sistema: {sistema}")
            print(f"   Componente: {componente}")
            print(f"   Modo de falla: {modo_falla}")
            print(f"   Descripción: {descripcion}")
            print(f"   📋 UUID: {taxonomia_id}")
            print()

print("=" * 80)
print("💡 Copia el UUID y actualiza en cargar_ot_final.py:")
print('   EVENTO_FRENOS = {')
print('       "taxonomia_id": "AQUI_PEGA_EL_UUID",')
print('       ...')
print("=" * 80)
