"""
Módulo de conexión a Supabase PostgreSQL.
Carga credenciales desde .env o .env.local
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# ============================================================
# CARGA DE VARIABLES DE ENTORNO
# ============================================================

proyecto_root = Path(__file__).parent.parent  # Desde src/db.py → raíz
env_local = proyecto_root / ".env.local"
env_default = proyecto_root / ".env"

if env_local.exists():
    load_dotenv(dotenv_path=env_local, override=True)
    print(f"✓ Variables de entorno cargadas desde: {env_local.name}")
elif env_default.exists():
    load_dotenv(dotenv_path=env_default, override=True)
    print(f"✓ Variables de entorno cargadas desde: {env_default.name}")
else:
    raise RuntimeError(
        f"ERROR: No se encontró .env.local ni .env en {proyecto_root}\n"
        f"Crea un archivo .env en la raíz del proyecto con:\n"
        f"  DATABASE_URL=postgresql://...\n"
        f"  SUPABASE_URL=https://...\n"
        f"  SUPABASE_SERVICE_ROLE_KEY=..."
    )

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "ERROR: DATABASE_URL no está definida en el archivo .env\n"
        "Verifica que el archivo contiene la variable correctamente."
    )

# ============================================================
# CREAR ENGINE DE SQLALCHEMY
# ============================================================
engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,
    pool_recycle=3600  # Recicla conexiones cada hora
)


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

def test_connection() -> bool:
    """
    Prueba la conexión a Supabase.
    Retorna True si es exitosa, False si falla.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT NOW()"))
            timestamp = result.scalar()
            print(f"✅ Conexión exitosa a Supabase: {timestamp}")
            return True
    except Exception as e:
        print(f"❌ Error de conexión a Supabase: {e}")
        return False


def get_engine() -> Engine:
    """Retorna la instancia del engine de SQLAlchemy."""
    return engine


# ============================================================
# PRUEBA CUANDO SE EJECUTA DIRECTAMENTE
# ============================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("PRUEBA DE CONEXIÓN A SUPABASE")
    print("="*70 + "\n")
    
    success = test_connection()
    
    if success:
        print("\n✓ Conexión verificada. Archivo db.py está listo para usar.\n")
    else:
        print("\n✗ No se pudo conectar. Verifica el archivo .env.\n")
