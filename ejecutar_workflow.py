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
    from limpiar_datos_completo import limpiar_datos_completo
    print("✅ Importado: limpiar_datos_completo")

    limpiar_datos_completo()
    print("✅ FASE 1 COMPLETADA: Base de datos limpiada\n")

except ImportError as e:
    print(f"❌ ERROR de importación: {e}")
    print("   Verifica que limpiar_datos_completo.py exista")
    sys.exit(1)

except Exception as e:
    print(f"❌ ERROR en limpieza: {e}")
    sys.exit(1)

# ============================================================
# FASE 2: CARGAR DATOS
# ============================================================

print("\n### FASE 2: CARGA DE DATOS ###")
print("-"*70)

try:
    from carga_datos_ordenado import carga_datos_ordenado
    print("✅ Importado: carga_datos_ordenado")

    carga_datos_ordenado(
        ruta_csv_activos='data/raw/activos.csv',
        ruta_csv_ot='data/raw/ordenes_trabajo.csv',
        ruta_csv_repuestos='data/raw/repuestos_consumidos.csv'
    )
    print("✅ FASE 2 COMPLETADA: Datos cargados\n")

except ImportError as e:
    print(f"❌ ERROR de importación: {e}")
    print("   Verifica que carga_datos_ordenado.py exista")
    sys.exit(1)

except Exception as e:
    print(f"❌ ERROR en carga: {e}")
    sys.exit(1)

# ============================================================
# FASE 3: VALIDAR INTEGRIDAD
# ============================================================

print("\n### FASE 3: VALIDACIÓN DE INTEGRIDAD ###")
print("-"*70)

try:
    from validar_integridad_datos import validar_integridad_datos
    print("✅ Importado: validar_integridad_datos")

    es_valido = validar_integridad_datos()

    if es_valido:
        print("✅ FASE 3 COMPLETADA: Integridad validada\n")
    else:
        print("❌ FASE 3 FALLÓ: Errores de integridad encontrados")
        sys.exit(1)

except ImportError as e:
    print(f"❌ ERROR de importación: {e}")
    print("   Verifica que validar_integridad_datos.py exista")
    sys.exit(1)

except Exception as e:
    print(f"❌ ERROR en validación: {e}")
    sys.exit(1)

# ============================================================
# FASE 4: GENERAR FEATURES (reutiliza build_features.py)
# ============================================================

print("\n### FASE 4: GENERACIÓN DE PANEL TEMPORAL ###")
print("-"*70)

try:
    from src.features.feature_pipeline import FeaturePipeline
    print("✅ Importado: FeaturePipeline")

    pipeline = FeaturePipeline()
    features = pipeline.ejecutar(dias_hacia_atras=180, paso=30)
    
    print("✅ FASE 4 COMPLETADA: Panel temporal generado\n")

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
print("\n📋 Próximos pasos:")
print("   1. Entrenar modelos:")
print("      uv run python entrenar_modelos.py")
print("   2. Generar predicciones:")
print("      uv run python ejecutar_scoring.py")
print("   3. Ver dashboard:")
print("      uv run streamlit run dashboard.py")
print("="*70)

sys.exit(0)
