"""
Limpia TODA la base de datos en el orden CORRECTO para evitar 
violaciones de clave foránea.
"""

from pathlib import Path
from dotenv import load_dotenv
import os
from sqlalchemy import create_engine, text

# Cargar .env desde la raíz del proyecto directamente
env_path = Path(__file__).parent / ".env"
if not env_path.exists():
    env_path = Path(__file__).parent / ".env.local"

if not env_path.exists():
    raise RuntimeError(f"No se encontró .env ni .env.local en {Path(__file__).parent}")

load_dotenv(dotenv_path=env_path, override=True)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no está definida en el archivo .env")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def limpiar_datos_completo():
    """
    Limpia TODA la base de datos en el orden CORRECTO para evitar 
    violaciones de clave foránea.

    Orden de eliminación (inverso de creación):
    1. scoring_resultados (sin FK pero depende lógicamente)
    2. repuestos_consumidos (FK → ordenes_trabajo)
    3. ordenes_trabajo (FK → activos)
    4. activos (base)
    5. modelos_registro (independiente pero la limpias)
    6. audit_log (independiente)

    Las vistas se recrean automáticamente.
    """
    try:
        conn = engine.connect()
        trans = conn.begin()

        print("🧹 Iniciando limpieza de base de datos...")

        # 1. SCORING_RESULTADOS (primera porque depende lógicamente)
        conn.execute(text("TRUNCATE TABLE scoring_resultados CASCADE;"))
        print("✅ scoring_resultados truncada")

        # 2. REPUESTOS_CONSUMIDOS (depende de ORDENES_TRABAJO)
        conn.execute(text("TRUNCATE TABLE repuestos_consumidos CASCADE;"))
        print("✅ repuestos_consumidos truncada")

        # 3. ORDENES_TRABAJO (depende de ACTIVOS)
        conn.execute(text("TRUNCATE TABLE ordenes_trabajo CASCADE;"))
        print("✅ ordenes_trabajo truncada")

        # 4. ACTIVOS (tabla base - NO CASCADE necesario aquí)
        conn.execute(text("TRUNCATE TABLE activos CASCADE;"))
        print("✅ activos truncada")

        # 5. MODELOS_REGISTRO (independiente)
        conn.execute(text("TRUNCATE TABLE modelos_registro CASCADE;"))
        print("✅ modelos_registro truncada")

        # 6. AUDIT_LOG (independiente)
        conn.execute(text("TRUNCATE TABLE audit_log CASCADE;"))
        print("✅ audit_log truncada")

        trans.commit()
        conn.close()
        print("✅ LIMPIEZA COMPLETADA - Base de datos vacía")

    except Exception as e:
        print(f"❌ ERROR en limpieza: {str(e)}")
        raise
