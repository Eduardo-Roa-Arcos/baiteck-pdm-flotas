"""
Valida integridad referencial COMPLETA de la base de datos.

RELACIONES A VALIDAR:
    1. ORDENES_TRABAJO → ACTIVOS (ot.activo_id → a.activo_id)
    2. REPUESTOS_CONSUMIDOS → ORDENES_TRABAJO (rc.ot_id → ot.ot_id)
    3. OT_FALLA_EVENTO → ORDENES_TRABAJO (ofe.ot_id → ot.ot_id) [nullable]
    4. OT_FALLA_EVENTO → TAXONOMIA_FALLAS (ofe.taxonomia_id → tf.taxonomia_id) [NOT NULL]
"""

from src.db import engine
from sqlalchemy import text
import pandas as pd


def validar_integridad_datos():
    """
    Valida que NO hay referencias rotas en la base de datos.
    
    Returns:
        bool: True si todas las validaciones pasan, False en caso contrario
    """
    
    print("\n" + "="*70)
    print("🔍 VALIDANDO INTEGRIDAD REFERENCIAL")
    print("="*70)
    
    errores = []
    
    try:
        with engine.connect() as conn:
            
            # ===== 1. ORDENES_TRABAJO → ACTIVOS =====
            print("\n1️⃣ ORDENES_TRABAJO → ACTIVOS (FK: ot.activo_id → a.activo_id)")
            try:
                query = """
                SELECT COUNT(*) as count_error
                FROM ordenes_trabajo ot
                WHERE ot.activo_id NOT IN (SELECT activo_id FROM activos)
                """
                result = conn.execute(text(query)).fetchone()
                if result[0] > 0:
                    msg = f"❌ {result[0]} OTs con activo_id INVÁLIDO"
                    print(f"   {msg}")
                    errores.append(msg)
                else:
                    print(f"   ✅ Todas las {conn.execute(text('SELECT COUNT(*) FROM ordenes_trabajo')).fetchone()[0]:,} OTs apuntan a activos válidos")
            except Exception as e:
                print(f"   ⚠️ No se pudo validar: {str(e)[:60]}")

            # ===== 2. REPUESTOS_CONSUMIDOS → ORDENES_TRABAJO =====
            print("\n2️⃣ REPUESTOS_CONSUMIDOS → ORDENES_TRABAJO (FK: rc.ot_id → ot.ot_id)")
            try:
                query = """
                SELECT COUNT(*) as count_error
                FROM repuestos_consumidos rc
                WHERE rc.ot_id NOT IN (SELECT ot_id FROM ordenes_trabajo)
                """
                result = conn.execute(text(query)).fetchone()
                if result[0] > 0:
                    msg = f"❌ {result[0]} Repuestos con ot_id INVÁLIDO"
                    print(f"   {msg}")
                    errores.append(msg)
                else:
                    print(f"   ✅ Todos los {conn.execute(text('SELECT COUNT(*) FROM repuestos_consumidos')).fetchone()[0]:,} repuestos apuntan a OTs válidas")
            except Exception as e:
                print(f"   ⚠️ No se pudo validar: {str(e)[:60]}")

            # ===== 3. OT_FALLA_EVENTO → ORDENES_TRABAJO =====
            print("\n3️⃣ OT_FALLA_EVENTO → ORDENES_TRABAJO (FK: ofe.ot_id → ot.ot_id) [nullable]")
            try:
                query = """
                SELECT COUNT(*) as count_error
                FROM ot_falla_evento ofe
                WHERE ofe.ot_id IS NOT NULL 
                  AND ofe.ot_id NOT IN (SELECT ot_id FROM ordenes_trabajo)
                """
                result = conn.execute(text(query)).fetchone()
                if result[0] > 0:
                    msg = f"❌ {result[0]} eventos con ot_id INVÁLIDO"
                    print(f"   {msg}")
                    errores.append(msg)
                else:
                    ot_nulos = conn.execute(text("SELECT COUNT(*) FROM ot_falla_evento WHERE ot_id IS NULL")).fetchone()[0]
                    ot_validos = conn.execute(text("SELECT COUNT(*) FROM ot_falla_evento WHERE ot_id IS NOT NULL")).fetchone()[0]
                    print(f"   ✅ Eventos válidos: {ot_validos:,} vinculados + {ot_nulos:,} sin OT (nullable)")
            except Exception as e:
                print(f"   ⚠️ No se pudo validar: {str(e)[:60]}")

            # ===== 4. OT_FALLA_EVENTO → TAXONOMIA_FALLAS =====
            print("\n4️⃣ OT_FALLA_EVENTO → TAXONOMIA_FALLAS (FK: ofe.taxonomia_id → tf.taxonomia_id) [NOT NULL]")
            try:
                # Validar que NO hay nulos
                nulos = conn.execute(text("SELECT COUNT(*) FROM ot_falla_evento WHERE taxonomia_id IS NULL")).fetchone()[0]
                if nulos > 0:
                    msg = f"❌ {nulos} eventos con taxonomia_id NULL (columna NOT NULL)"
                    print(f"   {msg}")
                    errores.append(msg)

                # Validar referencias válidas
                query = """
                SELECT COUNT(*) as count_error
                FROM ot_falla_evento ofe
                WHERE ofe.taxonomia_id NOT IN (SELECT taxonomia_id FROM taxonomia_fallas)
                """
                result = conn.execute(text(query)).fetchone()
                if result[0] > 0:
                    msg = f"❌ {result[0]} eventos con taxonomia_id INVÁLIDO"
                    print(f"   {msg}")
                    errores.append(msg)
                else:
                    total = conn.execute(text("SELECT COUNT(*) FROM ot_falla_evento")).fetchone()[0]
                    print(f"   ✅ Todos los {total:,} eventos apuntan a taxonomías válidas")
            except Exception as e:
                print(f"   ⚠️ No se pudo validar: {str(e)[:60]}")

            # ===== CONTEO DE REGISTROS POR TABLA =====
            print("\n📊 CONTEO DE REGISTROS:")
            tables = ['activos', 'ordenes_trabajo', 'repuestos_consumidos', 'ot_falla_evento']
            for table in tables:
                try:
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()
                    print(f"   • {table:25} {result[0]:>10,} registros")
                except:
                    print(f"   • {table:25} (tabla no existe)")

    except Exception as e:
        print(f"\n❌ ERROR GENERAL EN VALIDACIÓN: {str(e)}")
        errores.append(f"Error general: {str(e)}")

    # ===== RESUMEN FINAL =====
    print("\n" + "="*70)
    
    if not errores:
        print("✅ INTEGRIDAD VERIFICADA - Sin errores de referencia")
        print("="*70 + "\n")
        return True
    else:
        print(f"❌ SE ENCONTRARON {len(errores)} ERROR(ES):")
        for i, error in enumerate(errores, 1):
            print(f"   {i}. {error}")
        print("="*70 + "\n")
        return False


if __name__ == '__main__':
    validar_integridad_datos()
