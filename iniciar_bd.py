#!/usr/bin/env python3

import sys

print("=" * 70)
print("INICIALIZADOR DE BD: BAITECK-PDM-FLOTAS")
print("=" * 70)

# Paso 1: Importar engine
print("\n1. Importando engine de main.py...")
try:
    from src.db import engine
    print("   OK - Engine importado")
except Exception as e:
    print(f"   ERROR: {e}")
    sys.exit(1)

# Paso 2: Limpiar
print("\n2. Limpiando base de datos...")
try:
    from limpiar_datos_completo import limpiar_datos_completo
    limpiar_datos_completo()
    print("   OK - Limpieza completada")
except Exception as e:
    print(f"   ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Paso 3: Cargar
print("\n3. Cargando datos...")
try:
    from carga_datos_ordenado import carga_datos_ordenado
    carga_datos_ordenado(
        ruta_csv_activos='data/raw/activos.csv',
        ruta_csv_ot='data/raw/ordenes_trabajo.csv',
        ruta_csv_repuestos='data/raw/repuestos_consumidos.csv'
    )
    print("   OK - Carga completada")
except Exception as e:
    print(f"   ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Paso 4: Validar
print("\n4. Validando integridad...")
try:
    from validar_integridad_datos import validar_integridad_datos
    validar_integridad_datos()
    print("   OK - Validacion completada")
except Exception as e:
    print(f"   ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 70)
print("BASE DE DATOS INICIALIZADA CORRECTAMENTE")
print("=" * 70)
print("\nProximos pasos:")
print("  1. uv run python entrenar_modelos.py")
print("  2. uv run python ejecutar_scoring.py")
print("  3. uv run streamlit run dashboard.py")
print("=" * 70)
