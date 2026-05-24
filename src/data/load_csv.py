from pathlib import Path
import pandas as pd
from sqlalchemy import text
from src.db import engine

RAW_DIR = Path("data/raw")

# Esquema esperado para cada tabla
EXPECTED_COLUMNS = {
    "activos": ["id", "nombre", "tipo", "marca", "modelo", "año_fabricacion", "estado"],
    "ordenes_trabajo": ["id", "activo_id", "descripcion", "fecha_creacion", "fecha_cierre", "estado", "tecnico"],
    "repuestos_consumidos": ["id", "orden_trabajo_id", "repuesto", "cantidad", "precio_unitario"]
}

def validate_columns(df: pd.DataFrame, table_name: str) -> bool:
    """Valida que el CSV tenga las columnas esperadas"""
    expected = EXPECTED_COLUMNS.get(table_name, [])
    missing = set(expected) - set(df.columns)
    extra = set(df.columns) - set(expected)

    if missing:
        print(f"❌ Columnas faltantes en {table_name}: {missing}")
        return False
    if extra:
        print(f"⚠️  Columnas extra en {table_name} (se ignorarán): {extra}")

    return True

def load_table(csv_name: str, table_name: str, if_exists: str = "append") -> bool:
    """
    Carga un CSV a Supabase con validación
    """
    try:
        path = RAW_DIR / csv_name

        if not path.exists():
            print(f"❌ Archivo no encontrado: {path}")
            return False

        # Leer CSV
        df = pd.read_csv(path)
        print(f"📄 CSV leído: {csv_name} ({len(df)} filas)")

        # Validar columnas
        if not validate_columns(df, table_name):
            return False

        # Seleccionar solo columnas esperadas
        expected = EXPECTED_COLUMNS.get(table_name, [])
        df = df[expected]

        # Cargar a base de datos
        df.to_sql(
            table_name,
            engine,
            if_exists=if_exists,
            index=False,
            method="multi",
            chunksize=1000
        )

        print(f"✅ Cargados {len(df)} registros en {table_name}")
        return True

    except Exception as e:
        print(f"❌ Error al cargar {csv_name}: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Iniciando carga de archivos CSV...\n")

    # Cargar en orden de dependencias
    load_table("activos.csv", "activos", if_exists="replace")
    load_table("ordenes_trabajo.csv", "ordenes_trabajo", if_exists="replace")
    # load_table("repuestos_consumidos.csv", "repuestos_consumidos", if_exists="replace")

    print("\n✨ Carga completada")
