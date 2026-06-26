#!/usr/bin/env python3
"""
LIMPIAR DATOS DERIVADOS
========================

Limpia SOLO las tablas derivadas/transaccionales del workflow.
NO toca las tablas base (activos, ordenes_trabajo, ot_falla_evento, etc.)

Tablas que LIMPIA (derivadas):
- scoring_resultados
- disponibilidad_diaria
- audit_log
- modelos_registro
- features_activo_fecha
- auditoria_calidad_datos
- alertas

Tablas que PROTEGE (base + paramétricas):
- activos (maestra)
- taxonomia_fallas (paramétrica)
- modo_falla (paramétrica)
- equivalencia_nomenclatura (paramétrica)
- repuestos_maestro (paramétrica)
- usuarios (paramétrica)
- ordenes_trabajo (base)
- ot_falla_evento (base)
- repuestos_consumidos (base)
- feedback_taller (base)

Función: limpiar_datos_derivados()

Uso en workflow:
    from limpiar_datos_derivados import limpiar_datos_derivados
    limpiar_datos_derivados()

Uso directo:
    uv run python limpiar_datos_derivados.py
"""

import os
import sys
from pathlib import Path
from sqlalchemy import create_engine, text, inspect
from dotenv import load_dotenv

# Cargar variables de entorno
env_path = Path(__file__).parent / ".env"
if not env_path.exists():
    raise RuntimeError(f"No se encontró archivo .env en {Path(__file__).parent}")

load_dotenv(dotenv_path=env_path, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no definida en .env")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def limpiar_datos_derivados():
    """
    ⭐ FUNCIÓN PRINCIPAL
    Limpia SOLO tablas derivadas del workflow.
    
    NUNCA toca tablas base:
    - activos
    - taxonomia_fallas
    - modo_falla
    - equivalencia_nomenclatura
    - repuestos_maestro
    - usuarios
    - ordenes_trabajo
    - ot_falla_evento
    - repuestos_consumidos
    - feedback_taller
    """
    
    print("="*70)
    print("🧹 LIMPIEZA DE TABLAS DERIVADAS (WORKFLOW)")
    print("="*70 + "\n")

    # ============================================================
    # Tablas a limpiar (derivadas del workflow)
    # ============================================================

    TABLAS_A_LIMPIAR = [
        # ("scoring_resultados", "Resultados de scoring"),  # ⭐ PRESERVAR HISTÓRICO
        ("disponibilidad_diaria", "Disponibilidad histórica"),
        ("audit_log", "Log de auditoría"),
        ("modelos_registro", "Registro de modelos"),
        ("features_activo_fecha", "Features por activo/fecha"),
        ("auditoria_calidad_datos", "Auditoría de calidad"),
        ("alertas", "Alertas del sistema"),
    ]

    TABLAS_PROTEGIDAS = {
        'activos',
        'taxonomia_fallas',
        'modo_falla',
        'equivalencia_nomenclatura',
        'repuestos_maestro',
        'usuarios',
        'ordenes_trabajo',
        'ot_falla_evento',
        'repuestos_consumidos',
        'feedback_taller',
    }

    # ============================================================
    # PASO 1: Detectar tablas en BD
    # ============================================================

    print("1️⃣ Detectando tablas en BD...")

    try:
        inspector = inspect(engine)
        tablas_bd = set(inspector.get_table_names())
        print(f"   ✅ {len(tablas_bd)} tablas encontradas en BD\n")
    except Exception as e:
        print(f"   ❌ ERROR al inspeccionar BD: {e}\n")
        return False

    # ============================================================
    # PASO 2: Validar que tablas protegidas NO se tocan
    # ============================================================

    print("2️⃣ Verificando tablas protegidas...")
    
    protegidas_en_bd = TABLAS_PROTEGIDAS & tablas_bd
    print(f"   ✅ {len(protegidas_en_bd)} tablas protegidas (NO se tocarán):")
    for tabla in sorted(protegidas_en_bd):
        print(f"      • {tabla}")
    print()

    # ============================================================
    # PASO 3: Limpiar SOLO tablas derivadas
    # ============================================================

    print("3️⃣ Borrando tablas derivadas...\n")

    try:
        with engine.connect() as conn:
            trans = conn.begin()
            
            for tabla, descripcion in TABLAS_A_LIMPIAR:
                if tabla not in tablas_bd:
                    print(f"   ⊘  {tabla:30s} | no existe")
                    continue
                
                try:
                    conn.execute(text(f"DELETE FROM {tabla};"))
                    
                    # Verificar que quedó vacía
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {tabla}")).fetchone()
                    n_restantes = result[0] if result else 0
                    
                    if n_restantes == 0:
                        print(f"   ✅ {tabla:30s} | vaciada")
                    else:
                        print(f"   ⚠️  {tabla:30s} | {n_restantes} registros restantes")
                        
                except Exception as e:
                    error_msg = str(e)
                    print(f"   ⚠️  {tabla:30s} | {error_msg[:40]}")
            
            trans.commit()
            print(f"\n   ✅ Transacción completada\n")
            
    except Exception as e:
        print(f"\n   ❌ ERROR en transacción: {e}\n")
        return False

    # ============================================================
    # PASO 4: Validación final
    # ============================================================

    print("4️⃣ Validando estado final...\n")

    try:
        with engine.connect() as conn:
            print("   Tablas BASE (deben mantener datos intactos):")
            for tabla in ['activos', 'ordenes_trabajo', 'ot_falla_evento']:
                if tabla in tablas_bd:
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {tabla}")).fetchone()
                    n = result[0] if result else 0
                    print(f"      {tabla:30s}: {n:6,} registros ✅")
            
            print(f"\n   Tablas DERIVADAS (deben estar vacías):")
            for tabla, _ in TABLAS_A_LIMPIAR:
                if tabla in tablas_bd:
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {tabla}")).fetchone()
                    n = result[0] if result else 0
                    estado = "✅ VACÍA" if n == 0 else "❌ TIENE DATOS"
                    print(f"      {tabla:30s}: {n:6,} registros {estado}")
        print()
    except Exception as e:
        print(f"   ⚠️ Error en validación: {e}\n")

    # ============================================================
    # RESUMEN
    # ============================================================

    print("="*70)
    print("✅ LIMPIEZA COMPLETADA")
    print("="*70)
    print(f"\n✅ Tablas BASE: PROTEGIDAS (no se tocaron)")
    print(f"✅ Tablas DERIVADAS: BORRADAS (listas para regenerar)\n")
    
    return True


# ============================================================
# SI SE EJECUTA DIRECTAMENTE
# ============================================================

if __name__ == "__main__":
    success = limpiar_datos_derivados()
    sys.exit(0 if success else 1)
