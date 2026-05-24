# src/data/db.py
"""
Módulo de conexión a Supabase
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from pathlib import Path

# Cargar variables de entorno desde .env.local o .env (lo que exista)
proyecto_root = Path(__file__).parent.parent.parent
env_local = proyecto_root / ".env.local"
env_default = proyecto_root / ".env"

if env_local.exists():
    load_dotenv(dotenv_path=env_local, override=True)
    print(f"✓ Variables cargadas desde {env_local.name}")
elif env_default.exists():
    load_dotenv(dotenv_path=env_default, override=True)
    print(f"✓ Variables cargadas desde {env_default.name}")
else:
    raise RuntimeError(
        f"No se encontró ni .env.local ni .env en {proyecto_root}"
    )

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no está definida en el archivo de entorno cargado")

engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False
)


def test_connection() -> None:
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT NOW()"))
            timestamp = result.scalar()
            print(f"✅ Conexión OK a Supabase: {timestamp}")
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        raise


def get_engine() -> Engine:
    return engine


if __name__ == "__main__":
    test_connection()
