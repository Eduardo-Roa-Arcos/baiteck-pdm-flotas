#!/usr/bin/env python3
"""
♻️ RESTAURAR BASE DE DATOS DESDE BACKUP
=======================================

Restaura datos desde archivos CSV/JSON creados por respaldar_base_datos.py

USO:
  uv run python restaurar_base_datos.py --backup ./backups/2024-06-14_02-00-00

OPCIONES:
  --backup PATH       Ruta al directorio de backup (requerido)
  --tabla NAME        Restaurar solo 1 tabla (ej: --tabla activos)
  --drop              Borrar tablas existentes antes de restaurar
  --test              Modo seco (no escribe en BD)
  --help              Muestra esta ayuda

NOTAS:
  • Las tablas deben existir (o usar --drop)
  • El schema debe ser compatible
  • Los SERIAL/secuencias se reinician automáticamente
  • Las Foreign Keys se respetan (orden de inserción importante)

ORDEN DE RESTAURACIÓN (automático):
  1. activos              (sin dependencias)
  2. taxonomia_fallas
  3. ordenes_trabajo      (FK a activos)
  4. ot_falla_evento      (FK a ordenes_trabajo)
  5. disponibilidad_diaria (FK a activos)
  6. scoring_resultados   (FK a activos)
  7. paneles
  8. repuestos_maestro
  9. repuestos_consumidos (FK a ordenes_trabajo)
  10. feedback_taller
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL no configurada en .env")
    sys.exit(1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Orden de restauración (respeta Foreign Keys)
TABLA_ORDER = [
    'activos',
    'taxonomia_fallas',
    'ordenes_trabajo',
    'ot_falla_evento',
    'disponibilidad_diaria',
    'scoring_resultados',
    'paneles',
    'repuestos_maestro',
    'repuestos_consumidos',
    'feedback_taller',
    'umbrales_prioridad',
]

# ============================================================================
# FUNCIONES
# ============================================================================

def find_backup_files(backup_path: Path, formato: str = 'csv') -> dict:
    """Encuentra archivos de backup. Retorna {tabla: ruta}."""
    ext = f".{formato}"
    files = {}
    
    if not backup_path.exists():
        print(f"❌ ERROR: Ruta no existe: {backup_path}")
        sys.exit(1)
    
    for archivo in backup_path.glob(f"*{ext}"):
        tabla = archivo.stem
        files[tabla] = archivo
    
    if not files:
        print(f"❌ ERROR: No hay archivos {ext} en {backup_path}")
        sys.exit(1)
    
    return files


def drop_table(tabla: str) -> bool:
    """Borra una tabla (si existe). Retorna True si tuvo éxito."""
    try:
        with engine.begin() as conn:
            # Primero desactiva FK constraints
            conn.execute(text("SET session_replication_role = 'replica'"))
            conn.execute(text(f"DROP TABLE IF EXISTS {tabla} CASCADE"))
            conn.execute(text("SET session_replication_role = 'origin'"))
        return True
    except Exception as e:
        print(f"   ⚠️ No se pudo borrar {tabla}: {e}")
        return False


def restore_table(tabla: str, ruta_archivo: Path, test_mode: bool = False) -> dict:
    """
    Restaura una tabla desde archivo.
    Retorna {tabla: nombre, filas: int, estado: str}.
    """
    try:
        # Leer archivo
        if ruta_archivo.suffix == '.csv':
            df = pd.read_csv(ruta_archivo)
        elif ruta_archivo.suffix == '.json':
            df = pd.read_json(ruta_archivo)
        else:
            return {'tabla': tabla, 'filas': 0, 'estado': f'❌ Formato desconocido'}
        
        if len(df) == 0:
            return {'tabla': tabla, 'filas': 0, 'estado': '✅ Vacío (0 filas)'}
        
        # Convertir tipos de datos (importante para datetime)
        for col in df.columns:
            if 'fecha' in col.lower() or 'date' in col.lower():
                df[col] = pd.to_datetime(df[col], errors='coerce')
        
        if not test_mode:
            # Escribir en BD
            df.to_sql(
                tabla,
                engine,
                if_exists='append',
                index=False,
                method='multi'
            )
        
        return {'tabla': tabla, 'filas': len(df), 'estado': '✅'}
    
    except Exception as e:
        return {'tabla': tabla, 'filas': 0, 'estado': f'❌ {str(e)[:60]}'}


def parse_arguments() -> dict:
    """Parsea argumentos."""
    parser = argparse.ArgumentParser(
        description='Restaurar base de datos desde backup'
    )
    parser.add_argument(
        '--backup',
        type=str,
        required=True,
        help='Ruta del directorio de backup'
    )
    parser.add_argument(
        '--tabla',
        type=str,
        default=None,
        help='Restaurar solo UNA tabla (ej: --tabla activos)'
    )
    parser.add_argument(
        '--drop',
        action='store_true',
        help='Borrar tablas existentes antes de restaurar'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Modo seco (no escribe en BD)'
    )
    
    return vars(parser.parse_args())


# ============================================================================
# MAIN
# ============================================================================

def main():
    args = parse_arguments()
    
    backup_path = Path(args['backup'])
    tabla_especifica = args['tabla']
    drop_tables = args['drop']
    test_mode = args['test']
    
    print("="*70)
    print("♻️ RESTAURAR BASE DE DATOS")
    print("="*70)
    print(f"\nBackup: {backup_path}")
    print(f"Modo: {'🧪 TEST (sin escribir en BD)' if test_mode else '💾 ESCRITURA EN BD'}")
    if tabla_especifica:
        print(f"Tabla: {tabla_especifica}")
    print()
    
    # 1) BUSCAR ARCHIVOS
    print("1️⃣ Buscando archivos de backup...")
    
    # Intentar CSV primero, luego JSON
    archivos = find_backup_files(backup_path, 'csv')
    if not archivos:
        archivos = find_backup_files(backup_path, 'json')
    
    print(f"   ✅ {len(archivos)} archivo(s) encontrado(s)\n")
    
    # 2) DETERMINAR TABLAS A RESTAURAR
    if tabla_especifica:
        if tabla_especifica not in archivos:
            print(f"❌ ERROR: No hay archivo para tabla '{tabla_especifica}'")
            print(f"   Tablas disponibles: {', '.join(sorted(archivos.keys()))}")
            sys.exit(1)
        tablas_a_restaurar = [tabla_especifica]
    else:
        # Restaurar en orden (FK-safe)
        tablas_a_restaurar = [t for t in TABLA_ORDER if t in archivos]
        # Agregar tablas que existan pero no estén en TABLA_ORDER
        for t in sorted(archivos.keys()):
            if t not in tablas_a_restaurar:
                tablas_a_restaurar.append(t)
    
    print(f"2️⃣ Restaurando {len(tablas_a_restaurar)} tabla(s) en orden...\n")
    
    # 3) BORRAR TABLAS (si aplica)
    if drop_tables and not test_mode:
        print("   ⚠️ Borrando tablas existentes...")
        for tabla in reversed(tablas_a_restaurar):  # Orden inverso (FK)
            print(f"      {tabla:30} ", end='')
            if drop_table(tabla):
                print("✅")
            else:
                print("⚠️")
        print()
    
    # 4) RESTAURAR TABLAS
    resultados = []
    for i, tabla in enumerate(tablas_a_restaurar, 1):
        sys.stdout.write(f"   {i}/{len(tablas_a_restaurar)}: {tabla:<30} ")
        sys.stdout.flush()
        
        ruta = archivos[tabla]
        resultado = restore_table(tabla, ruta, test_mode)
        
        print(f"{resultado['filas']:>8} filas | {resultado['estado']}")
        resultados.append(resultado)
    
    # 5) RESUMEN
    print("\n" + "="*70)
    print("📊 RESUMEN")
    print("="*70 + "\n")
    
    total_filas = 0
    total_exitosas = 0
    
    for r in resultados:
        emoji = "✅" if '✅' in r['estado'] else "❌"
        print(f"{emoji} {r['tabla']:<30} {r['filas']:>8} filas")
        total_filas += r['filas']
        if '✅' in r['estado']:
            total_exitosas += 1
    
    print(f"\n{'='*70}")
    print(f"Total: {total_exitosas}/{len(resultados)} tablas | {total_filas:,} filas\n")
    
    if test_mode:
        print("🧪 MODO TEST - No se escribió en la BD")
    else:
        print("💾 DATOS RESTAURADOS EN LA BD")
    
    # 6) VERIFICACIÓN
    if not test_mode:
        print("\n✅ RESTAURACIÓN COMPLETADA")
        print("\nPróximos pasos:")
        print("  1. Verifica que los datos se vea correctos en dashboard")
        print("  2. Ejecuta: uv run python ejecutar_nightly.py")
        print("  3. Monitorea que P1/P2 aparezcan correctamente")
    
    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    main()
