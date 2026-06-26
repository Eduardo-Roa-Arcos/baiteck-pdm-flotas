#!/usr/bin/env python3
"""
BAITECK-PDM-FLOTAS: Orquestador del Workflow Completo
Ejecuta: Limpieza → Carga → Validación → Entrenamiento → Scoring

Uso: uv run python ejecutar_workflow.py
"""

import sys
import os

print("="*70)
print("🚀 BAITECK-PDM-FLOTAS: WORKFLOW COMPLETO")
print("="*70)

# ============================================================
# FASE 1: LIMPIAR DATOS
# ============================================================

print("\n\n### FASE 1: LIMPIEZA DE BASE DE DATOS ###")
print("-"*70)

try:
    from limpiar_datos_derivados import limpiar_datos_derivados
    print("✅ Importado: limpiar_datos_derivados")

    limpiar_datos_derivados()
    print("✅ FASE 1 COMPLETADA: Base de datos limpiada\n")

except ImportError as e:
    print(f"❌ ERROR de importación: {e}")
    print("   Verifica que limpiar_datos_derivados.py exista")
    sys.exit(1)

except Exception as e:
    print(f"❌ ERROR en limpieza: {e}")
    sys.exit(1)

# ============================================================
# FASE 2: VALIDAR INTEGRIDAD
# ============================================================

print("\n### FASE 2: VALIDACIÓN DE INTEGRIDAD ###")
print("-"*70)

try:
    from validar_integridad_datos import validar_integridad_datos
    print("✅ Importado: validar_integridad_datos")

    es_valido = validar_integridad_datos()

    if es_valido:
        print("✅ FASE 2 COMPLETADA: Integridad validada\n")
    else:
        print("❌ FASE 2 FALLÓ: Errores de integridad encontrados")
        sys.exit(1)

except ImportError as e:
    print(f"❌ ERROR de importación: {e}")
    print("   Verifica que validar_integridad_datos.py exista")
    sys.exit(1)

except Exception as e:
    print(f"❌ ERROR en validación: {e}")
    sys.exit(1)

# ============================================================
# FASE 3: GENERAR FEATURES
# ============================================================

print("\n### FASE 3: GENERACIÓN DE FEATURES ###")
print("-"*70)

try:
    from src.features.feature_pipeline import FeaturePipeline
    print("✅ Importado: FeaturePipeline")

    pipeline = FeaturePipeline()
    features = pipeline.ejecutar(dias_hacia_atras=180, paso=30)
    
    print("✅ FASE 3 COMPLETADA: Features generados\n")

except ImportError as e:
    print(f"❌ ERROR de importación: {e}")
    print("   Verifica que src/features/feature_pipeline.py exista")
    sys.exit(1)

except Exception as e:
    print(f"❌ ERROR en generación de features: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================
# RESUMEN FINAL
# ============================================================

print("\n\n" + "="*70)
print("✅ WORKFLOW COMPLETADO EXITOSAMENTE")
print("="*70)
print("\n📋 Próximos pasos (en orden):")
print("   1. Calcular disponibilidad histórica:")
print("      uv run python crear_disponibilidad_diaria_FULL.py")
print("   2. Entrenar modelo:")
print("      uv run python -m src.models.train_xgboost")
print("   3. Generar predicciones (scoring):")
print("      uv run python ejecutar_scoring.py")
print("   4. Generar plan de repuestos y finanzas:")
print("      uv run python generar_plan_repuestos_financiero.py")
print("   5. Ver dashboard:")
print("      uv run streamlit run dashboard.py")
print("\n📅 Cron diario (después del workflow inicial, si hay nueva actividad):")
print("      0 2 * * * cd /Users/eduardoroa/baiteck-pdm-flotas && uv run python crear_disponibilidad_diaria_INCREMENTAL.py")
print("="*70)

sys.exit(0)
