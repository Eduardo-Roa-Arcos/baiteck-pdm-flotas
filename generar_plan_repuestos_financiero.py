#!/usr/bin/env python3
"""
GENERAR PLAN DE REPUESTOS Y FINANZAS
====================================

Convierte las predicciones del modelo en decisiones de stock y en pesos.
Es SOLO LECTURA: no modifica el esquema. Exporta un plan priorizado a CSV/Parquet.

Cruza tres señales:
  1. scoring_resultados  → qué activo va a fallar (probabilidad) y en qué
     sistema (sistema_en_riesgo, ya basado en taxonomía real).
  2. repuestos_maestro   → para ese sistema, qué SKUs se necesitan, su stock,
     lead time, costo y criticidad.
  3. repuestos_consumidos + ordenes_trabajo + ot_falla_evento/taxonomia
                         → cuánto cuesta históricamente una correctiva de ese
                           sistema y qué repuestos consume (demanda esperada).

Salida por (activo, sistema, sku):
  - demanda_esperada      = prob_falla × consumo_promedio_historico_del_sistema
  - costo_correctivo_est  = costo medio de una correctiva del sistema
  - costo_evitado_est     = prob_falla × costo_correctivo_est
  - holgura_stock         = stock_actual − demanda_esperada
  - accion                = REORDENAR_URGENTE / PREPARAR / MONITOREAR

Ejecutar:
  uv run python generar_plan_repuestos_financiero.py [--fecha YYYY-MM-DD] [--top 0]
"""

import os
import sys
import argparse
from datetime import datetime
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent
OUT_DIR = PROJECT_ROOT / "data" / "processed"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Prioridades que se consideran accionables.
PRIORIDADES_ACCION = {"P1_critica", "P2_alta"}


def _engine():
    load_dotenv()
    url = os.getenv("DATABASE_URL")
    if not url:
        print("❌ ERROR: DATABASE_URL no configurada en .env")
        sys.exit(1)
    return create_engine(url)


def cargar_scoring(engine, fecha=None) -> pd.DataFrame:
    """Carga el scoring de la fecha indicada (o la más reciente)."""
    if fecha:
        q = text("""
            SELECT activo_id, fecha_scoring, probabilidad_falla, prioridad, sistema_en_riesgo
            FROM scoring_resultados
            WHERE fecha_scoring = :f
        """)
        df = pd.read_sql(q, engine, params={'f': pd.Timestamp(fecha).date()})
    else:
        q = text("""
            SELECT activo_id, fecha_scoring, probabilidad_falla, prioridad, sistema_en_riesgo
            FROM scoring_resultados
            WHERE fecha_scoring = (SELECT MAX(fecha_scoring) FROM scoring_resultados)
        """)
        df = pd.read_sql(q, engine)
    return df


def costo_correctivo_por_sistema(engine) -> pd.DataFrame:
    """
    Costo medio de una OT correctiva por sistema, vía taxonomía.
    Devuelve columnas: sistema, costo_correctivo_medio.
    """
    try:
        q = text("""
            SELECT tf.sistema AS sistema,
                   AVG(ot.costo_total_clp) AS costo_correctivo_medio
            FROM ot_falla_evento ofe
            JOIN ordenes_trabajo ot   ON ofe.ot_id = ot.ot_id
            JOIN taxonomia_fallas tf  ON ofe.taxonomia_id = tf.taxonomia_id
            WHERE LOWER(ot.tipo_ot) IN ('correctiva','correctivo','emergency')
              AND ot.costo_total_clp IS NOT NULL
            GROUP BY tf.sistema
        """)
        df = pd.read_sql(q, engine)
    except Exception:
        df = pd.DataFrame(columns=['sistema', 'costo_correctivo_medio'])
    df['sistema'] = df['sistema'].astype(str).str.lower()
    return df


def consumo_promedio_por_sistema_sku(engine) -> pd.DataFrame:
    """
    Consumo promedio de cada SKU por OT correctiva de un sistema.
    Devuelve: sistema, sku, cantidad_media_por_ot.
    """
    try:
        q = text("""
            WITH correctivas_sistema AS (
                SELECT DISTINCT ot.ot_id, tf.sistema
                FROM ot_falla_evento ofe
                JOIN ordenes_trabajo ot  ON ofe.ot_id = ot.ot_id
                JOIN taxonomia_fallas tf ON ofe.taxonomia_id = tf.taxonomia_id
                WHERE LOWER(ot.tipo_ot) IN ('correctiva','correctivo','emergency')
            )
            SELECT cs.sistema AS sistema,
                   rc.sku AS sku,
                   SUM(rc.cantidad) / COUNT(DISTINCT cs.ot_id) AS cantidad_media_por_ot
            FROM correctivas_sistema cs
            JOIN repuestos_consumidos rc ON cs.ot_id = rc.ot_id
            WHERE rc.sku IS NOT NULL
            GROUP BY cs.sistema, rc.sku
        """)
        df = pd.read_sql(q, engine)
    except Exception:
        df = pd.DataFrame(columns=['sistema', 'sku', 'cantidad_media_por_ot'])
    df['sistema'] = df['sistema'].astype(str).str.lower()
    return df


def cargar_maestro(engine) -> pd.DataFrame:
    try:
        df = pd.read_sql("""
            SELECT sku, descripcion, sistema, componente, lead_time_dias_promedio,
                   costo_unitario_clp, stock_actual, stock_minimo, criticidad, activo
            FROM repuestos_maestro
            WHERE activo = TRUE
        """, engine)
    except Exception:
        df = pd.DataFrame()
    if not df.empty:
        df['sistema'] = df['sistema'].astype(str).str.lower()
    return df


def _expandir_sistemas(sistema_en_riesgo: str):
    """'Motor | Frenos' -> ['motor','frenos']; 'General'/None -> []."""
    if not sistema_en_riesgo or str(sistema_en_riesgo).strip().lower() in ('general', 'nan', 'none'):
        return []
    return [s.strip().lower() for s in str(sistema_en_riesgo).split('|') if s.strip()]


def construir_plan(scoring, maestro, costo_sis, consumo, lead_time_critico=15):
    """Genera el plan priorizado (activo × sistema × sku)."""
    filas = []
    costo_map = dict(zip(costo_sis['sistema'], costo_sis['costo_correctivo_medio'])) \
        if not costo_sis.empty else {}

    for _, s in scoring.iterrows():
        prob = float(s['probabilidad_falla'] or 0)
        prioridad = s['prioridad']
        accionable = (prioridad in PRIORIDADES_ACCION)
        sistemas = _expandir_sistemas(s.get('sistema_en_riesgo'))
        if not sistemas:
            continue

        for sistema in sistemas:
            costo_correctivo = costo_map.get(sistema)
            costo_evitado = (prob * costo_correctivo) if costo_correctivo else None

            # SKUs candidatos: del maestro para ese sistema.
            skus = maestro[maestro['sistema'] == sistema] if not maestro.empty else pd.DataFrame()
            if skus.empty:
                # Sin maestro para el sistema: fila informativa sin repuesto.
                filas.append({
                    'activo_id': s['activo_id'], 'sistema': sistema, 'sku': None,
                    'descripcion': None, 'probabilidad_falla': round(prob, 4),
                    'prioridad': prioridad,
                    'demanda_esperada': None, 'stock_actual': None,
                    'holgura_stock': None, 'lead_time_dias': None,
                    'costo_unitario_clp': None,
                    'costo_correctivo_est': costo_correctivo,
                    'costo_evitado_est': costo_evitado,
                    'accion': 'SIN_MAESTRO',
                })
                continue

            for _, r in skus.iterrows():
                # Demanda esperada del SKU para este activo.
                cm = consumo[(consumo['sistema'] == sistema) & (consumo['sku'] == r['sku'])] \
                    if not consumo.empty else pd.DataFrame()
                cant_media = float(cm['cantidad_media_por_ot'].iloc[0]) if not cm.empty else 1.0
                demanda = prob * cant_media

                stock = float(r['stock_actual']) if pd.notna(r['stock_actual']) else 0.0
                holgura = stock - demanda
                lt = float(r['lead_time_dias_promedio']) if pd.notna(r['lead_time_dias_promedio']) else 30.0

                # Regla de acción.
                if accionable and holgura < 0:
                    accion = 'REORDENAR_URGENTE'
                elif accionable and (holgura < demanda or lt >= lead_time_critico):
                    accion = 'PREPARAR'
                else:
                    accion = 'MONITOREAR'

                filas.append({
                    'activo_id': s['activo_id'], 'sistema': sistema, 'sku': r['sku'],
                    'descripcion': r.get('descripcion'),
                    'probabilidad_falla': round(prob, 4), 'prioridad': prioridad,
                    'demanda_esperada': round(demanda, 3),
                    'stock_actual': stock, 'holgura_stock': round(holgura, 3),
                    'lead_time_dias': lt,
                    'costo_unitario_clp': r.get('costo_unitario_clp'),
                    'costo_correctivo_est': costo_correctivo,
                    'costo_evitado_est': round(costo_evitado, 0) if costo_evitado else None,
                    'accion': accion,
                })

    plan = pd.DataFrame(filas)
    if plan.empty:
        return plan

    orden_accion = {'REORDENAR_URGENTE': 0, 'PREPARAR': 1, 'SIN_MAESTRO': 2, 'MONITOREAR': 3}
    plan['_o'] = plan['accion'].map(orden_accion).fillna(9)
    plan = plan.sort_values(
        ['_o', 'probabilidad_falla', 'costo_evitado_est'],
        ascending=[True, False, False]
    ).drop(columns='_o').reset_index(drop=True)
    return plan


def main():
    parser = argparse.ArgumentParser(description="Plan de repuestos y finanzas")
    parser.add_argument('--fecha', type=str, help='Fecha de scoring (YYYY-MM-DD). Default: más reciente')
    parser.add_argument('--top', type=int, default=0, help='Limitar a las N filas más prioritarias (0 = todas)')
    args = parser.parse_args()

    engine = _engine()

    print("="*70)
    print("💰 PLAN DE REPUESTOS Y FINANZAS")
    print("="*70 + "\n")

    print("1️⃣ Cargando scoring...")
    scoring = cargar_scoring(engine, args.fecha)
    if scoring.empty:
        print("   ⚠️ No hay scoring para esa fecha. Ejecuta ejecutar_scoring.py primero.")
        sys.exit(0)
    fecha_usada = scoring['fecha_scoring'].iloc[0]
    print(f"   ✅ {len(scoring)} activos (fecha {fecha_usada})\n")

    print("2️⃣ Cargando maestro de repuestos y costos históricos...")
    maestro = cargar_maestro(engine)
    costo_sis = costo_correctivo_por_sistema(engine)
    consumo = consumo_promedio_por_sistema_sku(engine)
    print(f"   ✅ Maestro: {len(maestro)} SKUs | Costos por sistema: {len(costo_sis)} | "
          f"Consumo hist.: {len(consumo)} combinaciones\n")

    if maestro.empty:
        print("   ⚠️ repuestos_maestro está vacío. El plan saldrá en modo reducido "
              "(sin recomendación de SKU). Pobla el maestro para activar stock/finanzas.\n")

    print("3️⃣ Construyendo plan priorizado...")
    plan = construir_plan(scoring, maestro, costo_sis, consumo)
    if plan.empty:
        print("   ⚠️ No hay activos con sistema_en_riesgo accionable. Plan vacío.")
        sys.exit(0)
    if args.top and args.top > 0:
        plan = plan.head(args.top)
    print(f"   ✅ {len(plan)} líneas de plan\n")

    # Resumen financiero
    urgentes = plan[plan['accion'] == 'REORDENAR_URGENTE']
    evitado_total = plan['costo_evitado_est'].dropna().sum()
    print("4️⃣ Resumen:")
    print(f"   • Líneas urgentes (REORDENAR_URGENTE): {len(urgentes)}")
    print(f"   • Costo evitado estimado (suma): ${evitado_total:,.0f} CLP")
    print(f"   • Activos accionables: {plan['activo_id'].nunique()}\n")

    # Exportar
    stamp = pd.Timestamp(fecha_usada).strftime('%Y%m%d')
    csv_path = OUT_DIR / f"plan_repuestos_{stamp}.csv"
    pq_path = OUT_DIR / f"plan_repuestos_{stamp}.parquet"
    plan.to_csv(csv_path, index=False)
    try:
        plan.to_parquet(pq_path, index=False)
    except Exception:
        pq_path = None

    print("5️⃣ Exportado:")
    print(f"   ✅ {csv_path}")
    if pq_path:
        print(f"   ✅ {pq_path}")
    print("\n" + "="*70)
    print("✅ PLAN GENERADO")
    print("="*70 + "\n")
    print("ℹ️  Validar contra datos reales: la calidad depende de que repuestos_maestro")
    print("    (stock, lead_time, costo) y los costos de OT estén poblados.\n")
    print("="*70)
    print("✅ PIPELINE DIARIO COMPLETADO")
    print("="*70)
    print("\n📊 Dashboard está siendo actualizado automáticamente en tiempo real.")
    print("   Visualiza: uv run streamlit run dashboard.py")
    print("\n📅 Próxima ejecución automática: 02:00 AM mañana")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
