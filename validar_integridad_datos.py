from src.db import engine
from sqlalchemy import text
import pandas as pd

def validar_integridad_datos():
    """
    Valida que NO hay referencias rotas en la base de datos.
    """
    try:
        print("\n🔍 Validando integridad referencial...")

        with engine.connect() as conn:
            # 1. Verificar activos orfos (no debería haber)
            print("\n1️⃣ Verificando referencias ORDENES_TRABAJO → ACTIVOS")
            query = """
            SELECT COUNT(*) as ot_no_encontradas
            FROM ordenes_trabajo ot
            WHERE ot.activo_id NOT IN (SELECT activo_id FROM activos)
            """
            result = conn.execute(text(query)).fetchone()
            if result[0] > 0:
                print(f"   ❌ ERROR: {result[0]} OTs con activo_id inválido")
                return False
            print("   ✅ Todas las OTs apuntan a activos válidos")

            # 2. Verificar repuestos orfos
            print("\n2️⃣ Verificando referencias REPUESTOS → ORDENES_TRABAJO")
            query = """
            SELECT COUNT(*) as rep_no_encontrados
            FROM repuestos_consumidos rc
            WHERE rc.ot_id NOT IN (SELECT ot_id FROM ordenes_trabajo)
            """
            result = conn.execute(text(query)).fetchone()
            if result[0] > 0:
                print(f"   ❌ ERROR: {result[0]} Repuestos con ot_id inválido")
                return False
            print("   ✅ Todos los Repuestos apuntan a OTs válidas")

            # 3. Contar registros
            print("\n3️⃣ Conteo de registros por tabla:")
            tables = ['activos', 'ordenes_trabajo', 'repuestos_consumidos']
            for table in tables:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()
                print(f"   • {table}: {result[0]} registros")

        print("\n✅ INTEGRIDAD VERIFICADA - Sin errores de referencia")
        return True

    except Exception as e:
        print(f"❌ ERROR en validación: {str(e)}")
        return False
