#!/usr/bin/env python3
"""
🔐 RESPALDAR BASE DE DATOS COMPLETA - BAITECK PDM-FLOTAS
========================================================

Exporta TODAS las tablas de Supabase a archivos CSV + schema SQL.

Salida:
  ./backups/
    ├─ YYYY-MM-DD_HH-MM-SS/
    │  ├─ schema_completo.sql          (DDL de todas las tablas)
    │  ├─ tabla_1.csv
    │  ├─ tabla_2.csv
    │  ├─ ...
    │  └─ resumen_backup.txt           (listado y conteos)

USO:
  uv run python respaldar_base_datos.py                    # Respalda todo
  uv run python respaldar_base_datos.py --tabla activos   # Solo 1 tabla
  uv run python respaldar_base_datos.py --formato json    # JSON en lugar de CSV

NOTA: El respaldo se guarda LOCAL. Para transportar a otro servidor,
      comprime la carpeta del backup y cópiala.
"""

import os
import sys
import argparse
from datetime import datetime
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, inspect, text
from dotenv import load_dotenv
import json

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL no configurada en .env")
    sys.exit(1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Crear directorio de backups
BACKUP_DIR = Path("./backups")
TIMESTAMP = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
BACKUP_PATH = BACKUP_DIR / TIMESTAMP
BACKUP_PATH.mkdir(parents=True, exist_ok=True)

print("="*70)
print("🔐 RESPALDO COMPLETO - BAITECK PDM-FLOTAS")
print("="*70)
print(f"\n📁 Ubicación: {BACKUP_PATH}\n")

# ============================================================================
# FUNCIONES
# ============================================================================

def get_all_tables() -> list:
    """Obtiene lista de todas las tablas de la BD."""
    inspector = inspect(engine)
    return inspector.get_table_names()


def export_schema() -> str:
    """
    Genera SQL DDL de todas las tablas.
    Usa información_schema de PostgreSQL.
    """
    query = text("""
        SELECT 
            schemaname,
            tablename,
            tableowner
        FROM pg_tables
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY tablename;
    """)
    
    with engine.connect() as conn:
        result = conn.execute(query).fetchall()
    
    tables = [row[1] for row in result]
    
    # Obtener DDL de cada tabla
    ddl_script = "-- ============================================================\n"
    ddl_script += "-- SCHEMA COMPLETO - BAITECK PDM-FLOTAS\n"
    ddl_script += f"-- Generado: {datetime.now().isoformat()}\n"
    ddl_script += "-- ============================================================\n\n"
    
    for table_name in tables:
        try:
            # Obtener DDL de la tabla
            query_ddl = text(f"""
                SELECT pg_get_create_table_as('{table_name}'::text);
            """)
            
            with engine.connect() as conn:
                result = conn.execute(query_ddl).fetchone()
            
            if result and result[0]:
                ddl_script += f"-- ============================================================\n"
                ddl_script += f"-- TABLA: {table_name}\n"
                ddl_script += f"-- ============================================================\n"
                ddl_script += result[0] + ";\n\n"
        except Exception as e:
            print(f"   ⚠️ No se pudo obtener DDL de {table_name}: {e}")
            continue
    
    return ddl_script


def export_table_to_csv(table_name: str, output_path: Path) -> dict:
    """Exporta tabla a CSV. Retorna {rows: int, size_mb: float}."""
    try:
        df = pd.read_sql_table(table_name, engine)
        csv_file = output_path / f"{table_name}.csv"
        df.to_csv(csv_file, index=False)
        
        size_mb = csv_file.stat().st_size / (1024 * 1024)
        return {
            'tabla': table_name,
            'filas': len(df),
            'columnas': len(df.columns),
            'size_mb': round(size_mb, 2),
            'archivo': csv_file.name,
            'estado': '✅'
        }
    except Exception as e:
        return {
            'tabla': table_name,
            'filas': 0,
            'columnas': 0,
            'size_mb': 0,
            'archivo': '-',
            'estado': f'❌ {str(e)[:50]}'
        }


def export_table_to_json(table_name: str, output_path: Path) -> dict:
    """Exporta tabla a JSON. Retorna {rows: int, size_mb: float}."""
    try:
        df = pd.read_sql_table(table_name, engine)
        json_file = output_path / f"{table_name}.json"
        
        # Convertir a JSON con manejo de tipos especiales
        df_json = df.copy()
        for col in df_json.columns:
            if pd.api.types.is_datetime64_any_dtype(df_json[col]):
                df_json[col] = df_json[col].astype(str)
        
        df_json.to_json(json_file, orient='records', indent=2)
        
        size_mb = json_file.stat().st_size / (1024 * 1024)
        return {
            'tabla': table_name,
            'filas': len(df),
            'columnas': len(df.columns),
            'size_mb': round(size_mb, 2),
            'archivo': json_file.name,
            'estado': '✅'
        }
    except Exception as e:
        return {
            'tabla': table_name,
            'filas': 0,
            'columnas': 0,
            'size_mb': 0,
            'archivo': '-',
            'estado': f'❌ {str(e)[:50]}'
        }


def generate_summary(resultados: list, formato: str) -> str:
    """Genera resumen del backup."""
    summary = f"""
{'='*70}
📊 RESUMEN DEL RESPALDO
{'='*70}

Fecha: {datetime.now().isoformat()}
Formato: {formato.upper()}
Ubicación: {BACKUP_PATH}

TABLA DE CONTENIDOS:
{'-'*70}
{'TABLA':<30} {'FILAS':>10} {'COLUMNAS':>10} {'SIZE (MB)':>12} {'ESTADO':<10}
{'-'*70}
"""
    
    total_filas = 0
    total_size = 0
    
    for r in resultados:
        summary += f"{r['tabla']:<30} {r['filas']:>10} {r['columnas']:>10} {r['size_mb']:>12.2f} {r['estado']:<10}\n"
        total_filas += r['filas']
        total_size += r['size_mb']
    
    summary += f"{'-'*70}\n"
    summary += f"{'TOTAL':<30} {total_filas:>10} {'':<10} {total_size:>12.2f}\n"
    summary += f"{'='*70}\n\n"
    
    summary += f"""
ARCHIVOS GENERADOS:
  ├─ schema_completo.sql       (DDL de todas las tablas)
  ├─ resumen_backup.txt        (este archivo)
  └─ *.{formato}               (datos de cada tabla)

RESTAURACIÓN:

Para restaurar en una BD nueva:

1. Crear BD vacía:
   createdb mi_nueva_bd

2. Cargar schema:
   psql -d mi_nueva_bd -f {BACKUP_PATH}/schema_completo.sql

3. Cargar datos (desde CSV):
   python restaurar_base_datos.py --backup {BACKUP_PATH}

O manualmente desde Python:
   import pandas as pd
   df = pd.read_csv('{BACKUP_PATH}/activos.csv')
   df.to_sql('activos', engine, if_exists='append', index=False)

NOTAS:
  • El schema SQL puede requerir ajustes de secuencias (SERIAL, etc)
  • Verifica Foreign Keys antes de restaurar (orden de tablas)
  • Los archivos CSV/JSON son legibles y editables manualmente

{'='*70}
"""
    
    return summary


def parse_arguments() -> dict:
    """Parsea argumentos."""
    parser = argparse.ArgumentParser(
        description='Respaldar base de datos Supabase completa'
    )
    parser.add_argument(
        '--tabla',
        type=str,
        default=None,
        help='Respaldar solo UNA tabla (ej: --tabla activos)'
    )
    parser.add_argument(
        '--formato',
        type=str,
        default='csv',
        choices=['csv', 'json'],
        help='Formato de salida: csv o json (default: csv)'
    )
    
    return vars(parser.parse_args())


# ============================================================================
# MAIN
# ============================================================================

def main():
    args = parse_arguments()
    formato = args['formato']
    tabla_especifica = args['tabla']
    
    print(f"Formato: {formato.upper()}")
    if tabla_especifica:
        print(f"Tabla: {tabla_especifica}")
    print()
    
    # 1) OBTENER LISTA DE TABLAS
    print("1️⃣ Obteniendo lista de tablas...")
    all_tables = get_all_tables()
    
    if tabla_especifica:
        if tabla_especifica not in all_tables:
            print(f"❌ ERROR: Tabla '{tabla_especifica}' no existe")
            print(f"   Tablas disponibles: {', '.join(all_tables)}")
            sys.exit(1)
        tables_to_export = [tabla_especifica]
    else:
        tables_to_export = all_tables
    
    print(f"   ✅ {len(tables_to_export)} tabla(s) a respaldar\n")
    
    # 2) EXPORTAR SCHEMA SQL
    print("2️⃣ Exportando schema SQL...")
    try:
        schema_sql = export_schema()
        schema_file = BACKUP_PATH / "schema_completo.sql"
        with open(schema_file, 'w') as f:
            f.write(schema_sql)
        print(f"   ✅ Guardado en: {schema_file.name}\n")
    except Exception as e:
        print(f"   ⚠️ No se pudo exportar schema: {e}\n")
    
    # 3) EXPORTAR TABLAS
    print(f"3️⃣ Exportando tablas ({formato.upper()})...")
    print(f"   {'-'*66}")
    
    resultados = []
    for i, table in enumerate(tables_to_export, 1):
        sys.stdout.write(f"\r   Tabla {i}/{len(tables_to_export)}: {table:<30} ")
        sys.stdout.flush()
        
        if formato == 'csv':
            resultado = export_table_to_csv(table, BACKUP_PATH)
        else:  # json
            resultado = export_table_to_json(table, BACKUP_PATH)
        
        resultados.append(resultado)
    
    print(f"\n   ✅ {len(resultados)} tabla(s) exportadas\n")
    
    # 4) GENERAR RESUMEN
    print("4️⃣ Generando resumen...")
    summary = generate_summary(resultados, formato)
    summary_file = BACKUP_PATH / "resumen_backup.txt"
    with open(summary_file, 'w') as f:
        f.write(summary)
    print(f"   ✅ Guardado en: {summary_file.name}\n")
    
    # 5) RESUMEN FINAL
    print("\n" + "="*70)
    print(f"✅ RESPALDO COMPLETADO")
    print("="*70)
    print(summary)


if __name__ == "__main__":
    main()
