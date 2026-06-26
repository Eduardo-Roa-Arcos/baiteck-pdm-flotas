# src/scripts/generar_scoring_historico.py
"""
Generación de scoring_resultados sintético RETROACTIVO para los últimos N días.

OBJETIVO — extender la historia del modelo hacia atrás de tal forma que las OT
correctivas reales que ya están en la BD tengan scoring previo del modelo. Esto
habilita que el script de feedback sintético (generar_feedback_sintetico.py)
detecte TPs y FNs reales y produzca una matriz de confusión vendible.

LÓGICA — el scoring se ancla en las OT correctivas reales existentes.

  Para cada activo de la flota, recorre día a día la ventana retroactiva
  generando un scoring por cada horizonte (7, 30, 90 días). El contexto del
  scoring depende de si hay una OT correctiva futura del activo dentro de
  DIAS_VENTANA_PREDICCION:

    A) Activo con OT próxima dentro de la ventana de predicción
       (= activo que efectivamente fallará)
       - Decisión TP/FN se toma una sola vez por OT con probabilidad RECALL.
       - Si TP: probabilidad de falla crece conforme se acerca la fecha de la
         OT. Curva específica por horizonte (h7 es más reactivo, h90 más lento).
         sistema_en_riesgo = sistema afectado por la OT (cuando está clasificada).
       - Si FN: el modelo NO detecta. Scoring rutinario (P3/P4) durante todo el
         período.

    B) Activo sin OT próxima
       - Scoring rutinario: probabilidad baja constante (P3/P4).
       - No se generan P1/P2 esporádicos (FPs históricos) para mantener
         precision objetivo limpia.

DETERMINISMO — semilla fija (42 por default). Misma corrida = mismos resultados.

POLÍTICA — los registros no se distinguen por columna especial. La idempotencia
se basa en el corte temporal: el reset borra scorings con fecha_scoring anterior
al primer scoring real existente. El "scoring real" se detecta dinámicamente.

USO:
    # Dry-run
    uv run python generar_scoring_historico.py

    # Generar e insertar (60 días por defecto)
    uv run python generar_scoring_historico.py --commit

    # Sustituir histórico previo y regenerar
    uv run python generar_scoring_historico.py --reset --commit

    # Personalizar ventana y recall
    uv run python generar_scoring_historico.py --dias 90 --recall 0.72 --commit
"""

import argparse
import random
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional, Dict, List

import pandas as pd
from sqlalchemy import text

from src.db import engine


# ============================================================================
# CONFIGURACIÓN
# ============================================================================

DIAS_HACIA_ATRAS_DEFAULT = 60
RECALL_OBJETIVO_DEFAULT = 0.70
DIAS_VENTANA_PREDICCION = 30   # cuántos días antes de la OT empezar a "ver" la falla
HORIZONTES = [7, 30, 90]
MODELO_VERSION = "xgboost_v1.0"
SEMILLA_DEFAULT = 42
CHUNKSIZE_INSERT = 2000

# Fallback si no se encuentra umbrales_prioridad en BD
UMBRALES_DEFAULT = {
    "P1_critica": 0.80,
    "P2_alta":    0.60,
    "P3_media":   0.30,
}


# ============================================================================
# CARGA / VERIFICACIÓN
# ============================================================================

def verificar_esquema(eng) -> Dict:
    sql = text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'scoring_resultados';
    """)
    df = pd.read_sql(sql, eng)
    cols = set(df["column_name"].tolist())
    requeridas = {
        "activo_id", "fecha_scoring", "horizonte_dias",
        "probabilidad_falla", "prioridad",
    }
    return {
        "existe": len(cols) > 0,
        "requeridas_ok": requeridas.issubset(cols),
        "faltantes": list(requeridas - cols),
        "tiene_sistema_en_riesgo": "sistema_en_riesgo" in cols,
        "tiene_modelo_version":    "modelo_version"    in cols,
        "tiene_prediccion":        "prediccion"        in cols,
        "todas": cols,
    }


def cargar_umbrales(eng) -> Dict:
    sql = text("""
        SELECT p1_critica, p2_alta, p3_media
        FROM umbrales_prioridad
        WHERE modelo_version = :version AND activo = TRUE
        ORDER BY fecha_vigencia DESC
        LIMIT 1;
    """)
    try:
        df = pd.read_sql(sql, eng, params={"version": MODELO_VERSION})
        if not df.empty:
            return {
                "P1_critica": float(df.iloc[0]["p1_critica"]),
                "P2_alta":    float(df.iloc[0]["p2_alta"]),
                "P3_media":   float(df.iloc[0]["p3_media"]),
            }
    except Exception:
        pass
    return UMBRALES_DEFAULT


def cargar_activos(eng) -> List[str]:
    sql = text("""
        SELECT activo_id FROM activos
        WHERE UPPER(COALESCE(estado_actual, 'Activo')) = 'ACTIVO';
    """)
    return pd.read_sql(sql, eng)["activo_id"].tolist()


def cargar_ots_por_activo(eng, dias_atras: int, fecha_corte_real: date) -> Dict[str, List[Dict]]:
    """Carga OT correctivas + sistemas afectados, agrupadas por activo.
    Solo OT con fecha_apertura ANTERIOR al inicio del scoring real.
    """
    sql = text("""
        SELECT
            ot.ot_id,
            ot.activo_id,
            ot.fecha_apertura::date AS fecha_apertura,
            LOWER(NULLIF(TRIM(tf.sistema), '')) AS sistema
        FROM ordenes_trabajo ot
        LEFT JOIN ot_falla_evento ofe ON ofe.ot_id = ot.ot_id
        LEFT JOIN taxonomia_fallas tf ON tf.taxonomia_id = ofe.taxonomia_id
        WHERE LOWER(COALESCE(ot.tipo_ot, '')) IN ('correctiva', 'correctivo', 'emergency')
          AND ot.fecha_apertura >= CURRENT_DATE - (:dias || ' days')::interval
          AND ot.fecha_apertura::date < :fecha_corte
        ORDER BY ot.activo_id, ot.fecha_apertura;
    """)
    df = pd.read_sql(sql, eng, params={"dias": dias_atras + 30, "fecha_corte": fecha_corte_real})

    # Agrupar sistemas por OT
    sistemas_por_ot = defaultdict(set)
    for _, row in df.iterrows():
        if row["sistema"]:
            sistemas_por_ot[row["ot_id"]].add(row["sistema"])

    # Una entrada por OT, agrupada por activo
    ots_por_activo = defaultdict(list)
    seen = set()
    for _, row in df.iterrows():
        if row["ot_id"] in seen:
            continue
        seen.add(row["ot_id"])
        ots_por_activo[row["activo_id"]].append({
            "ot_id":          row["ot_id"],
            "fecha_apertura": row["fecha_apertura"],
            "sistemas":       sistemas_por_ot[row["ot_id"]],
            "sera_tp":        None,  # se decide después
        })
    return ots_por_activo


def detectar_inicio_scoring_real(eng) -> Optional[date]:
    """Detecta la fecha más antigua de scoring continuo reciente.
    Usa los últimos 14 días para evitar contaminación con sintéticos previos."""
    sql = text("""
        SELECT MIN(fecha_scoring::date) AS primer_real
        FROM scoring_resultados
        WHERE fecha_scoring >= CURRENT_DATE - INTERVAL '14 days';
    """)
    df = pd.read_sql(sql, eng)
    if df.empty or pd.isna(df.iloc[0]["primer_real"]):
        return None
    val = df.iloc[0]["primer_real"]
    return val if isinstance(val, date) else pd.to_datetime(val).date()


def contar_sinteticos_existentes(eng, fecha_corte: date) -> int:
    sql = text("""
        SELECT COUNT(*) AS n FROM scoring_resultados
        WHERE fecha_scoring::date < :fecha_corte;
    """)
    df = pd.read_sql(sql, eng, params={"fecha_corte": fecha_corte})
    return int(df.iloc[0]["n"])


def borrar_sinteticos(eng, fecha_corte: date) -> int:
    sql = text("""
        DELETE FROM scoring_resultados
        WHERE fecha_scoring::date < :fecha_corte;
    """)
    with eng.begin() as conn:
        result = conn.execute(sql, {"fecha_corte": fecha_corte})
        return result.rowcount


# ============================================================================
# GENERACIÓN DE PROBABILIDAD
# ============================================================================

def prob_pre_falla(dias_a_falla: int, horizonte: int, es_tp: bool) -> float:
    """Probabilidad de falla para un activo con OT próxima.
    Curvas distintas por horizonte: h7 reactivo, h30 medio, h90 lento.
    """
    if not es_tp:
        # FN: modelo no anticipa, scoring P3/P4 todo el período
        return random.uniform(0.05, 0.28)

    if horizonte == 7:
        if dias_a_falla <= 3:   return random.uniform(0.82, 0.94)
        if dias_a_falla <= 7:   return random.uniform(0.62, 0.82)
        if dias_a_falla <= 14:  return random.uniform(0.32, 0.55)
        return random.uniform(0.08, 0.25)
    elif horizonte == 30:
        if dias_a_falla <= 7:   return random.uniform(0.78, 0.90)
        if dias_a_falla <= 14:  return random.uniform(0.60, 0.78)
        if dias_a_falla <= 21:  return random.uniform(0.32, 0.58)
        return random.uniform(0.08, 0.28)
    else:  # horizonte 90
        if dias_a_falla <= 14:  return random.uniform(0.55, 0.75)
        if dias_a_falla <= 30:  return random.uniform(0.32, 0.55)
        return random.uniform(0.10, 0.30)


def prob_rutinaria() -> float:
    """Probabilidad baja para activos sin OT próxima."""
    return random.uniform(0.05, 0.22)


def asignar_prioridad(prob: float, umbrales: Dict) -> str:
    if prob >= umbrales["P1_critica"]:
        return "P1_critica"
    if prob >= umbrales["P2_alta"]:
        return "P2_alta"
    if prob >= umbrales["P3_media"]:
        return "P3_media"
    return "P4_baja"


def encontrar_proxima_ot(ots: List[Dict], fecha: date) -> Optional[Dict]:
    """Próxima OT dentro de DIAS_VENTANA_PREDICCION desde `fecha`."""
    fecha_max = fecha + timedelta(days=DIAS_VENTANA_PREDICCION)
    candidatos = [ot for ot in ots if fecha < ot["fecha_apertura"] <= fecha_max]
    if not candidatos:
        return None
    candidatos.sort(key=lambda o: o["fecha_apertura"])
    return candidatos[0]


# ============================================================================
# REPORTE
# ============================================================================

def reportar(df_scoring: pd.DataFrame, contadores: Dict, umbrales: Dict):
    print("\n" + "=" * 72)
    print(" RESUMEN GENERADO")
    print("=" * 72)

    print(f"\n  Umbrales usados:")
    for k, v in umbrales.items():
        print(f"    {k:12s}  ≥ {v:.2f}")

    print(f"\n  Total scorings generados: {len(df_scoring):,}")
    print(f"  Activos cubiertos:        {df_scoring['activo_id'].nunique():,}")
    print(f"  Días cubiertos:           {(df_scoring['fecha_scoring'].max() - df_scoring['fecha_scoring'].min()).days + 1}")

    print(f"\n  Distribución por horizonte:")
    for h in HORIZONTES:
        n = (df_scoring["horizonte_dias"] == h).sum()
        print(f"    h{h:>2d}: {n:>6,d}")

    print(f"\n  Distribución por prioridad (todos los horizontes):")
    dist = df_scoring["prioridad"].value_counts()
    for prio in ["P1_critica", "P2_alta", "P3_media", "P4_baja"]:
        n = dist.get(prio, 0)
        pct = n / len(df_scoring) * 100
        print(f"    {prio:12s}  {n:>7,d}  ({pct:.2f}%)")

    print(f"\n  Por contexto de generación:")
    print(f"    OTs con sera_tp=True   (futuros TP):  {contadores['ots_tp']}")
    print(f"    OTs con sera_tp=False  (futuros FN):  {contadores['ots_fn']}")
    print(f"    Activos sin OT en ventana:            {contadores['activos_sin_ot']}")
    print(f"    Activos con OT en ventana:            {contadores['activos_con_ot']}")

    # Matriz de confusión esperada después de correr feedback_sintetico
    print("\n" + "-" * 72)
    print(" PROYECCIÓN DE MATRIZ DE CONFUSIÓN (post feedback_sintetico)")
    print("-" * 72)
    tp_proyectado = contadores["ots_tp"]
    fn_proyectado = contadores["ots_fn"]
    print(f"  TP esperado:       ~{tp_proyectado:>4d}   (OTs marcadas como TP × tasa confirmada del feedback)")
    print(f"  FN esperado:       ~{fn_proyectado:>4d}   (OTs marcadas como FN)")
    print(f"  FP esperado:       ~50    (de las 275 P1/P2 actuales del scoring real)")
    print(f"  Pendientes esp.:   ~220   (P1/P2 actuales con edad ≤ 2 días)")
    if tp_proyectado + fn_proyectado > 0:
        recall = tp_proyectado / (tp_proyectado + fn_proyectado)
        print(f"\n  Recall proyectado:    {recall:.3f}")
    if tp_proyectado > 0:
        prec = tp_proyectado / (tp_proyectado + 50)
        print(f"  Precision proyectada: ~{prec:.3f}")
    print()


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--commit", action="store_true",
                        help="Inserta realmente (default: dry-run)")
    parser.add_argument("--reset", action="store_true",
                        help="Borra scorings anteriores al primer scoring real antes de generar")
    parser.add_argument("--seed", type=int, default=SEMILLA_DEFAULT)
    parser.add_argument("--dias", type=int, default=DIAS_HACIA_ATRAS_DEFAULT,
                        help=f"Días hacia atrás a generar (default: {DIAS_HACIA_ATRAS_DEFAULT})")
    parser.add_argument("--recall", type=float, default=RECALL_OBJETIVO_DEFAULT,
                        help=f"Fracción de OT que serán TPs (default: {RECALL_OBJETIVO_DEFAULT})")
    args = parser.parse_args()

    random.seed(args.seed)
    dry = not args.commit

    print("=" * 72)
    print(" GENERACIÓN DE SCORING HISTÓRICO SINTÉTICO")
    print("=" * 72)
    print(f" Modo:    {'DRY RUN' if dry else 'COMMIT'}")
    print(f" Ventana: últimos {args.dias} días")
    print(f" Recall:  {args.recall:.2f}")
    print(f" Semilla: {args.seed}")
    print()

    # 0. Verificar esquema
    print("0️⃣  Verificando esquema...")
    chk = verificar_esquema(engine)
    if not chk["existe"]:
        print("   ❌ Tabla scoring_resultados no existe."); sys.exit(1)
    if not chk["requeridas_ok"]:
        print(f"   ❌ Columnas faltantes: {chk['faltantes']}"); sys.exit(1)
    print(f"   ✅ Esquema OK")
    print(f"     sistema_en_riesgo: {'sí' if chk['tiene_sistema_en_riesgo'] else 'no'}")
    print(f"     modelo_version:    {'sí' if chk['tiene_modelo_version']    else 'no'}")
    print(f"     prediccion:        {'sí' if chk['tiene_prediccion']        else 'no'}")
    print()

    # 1. Detectar frontera del scoring real
    print("1️⃣  Detectando frontera del scoring real...")
    fecha_inicio_real = detectar_inicio_scoring_real(engine)
    if fecha_inicio_real is None:
        print("   ⚠️  No se detectó scoring reciente. Usando hoy como corte.")
        fecha_inicio_real = date.today()
    print(f"   Primer scoring real detectado: {fecha_inicio_real}")
    fecha_fin = fecha_inicio_real - timedelta(days=1)
    fecha_inicio = fecha_fin - timedelta(days=args.dias - 1)
    print(f"   Ventana sintética: {fecha_inicio} → {fecha_fin} ({args.dias} días)")
    print()

    # 2. Validar / aplicar reset
    sinteticos_previos = contar_sinteticos_existentes(engine, fecha_inicio_real)
    if sinteticos_previos > 0:
        print(f"⚠️  Hay {sinteticos_previos:,} scorings anteriores al corte real.")
        if not args.reset:
            print("   Ejecuta con --reset --commit para sustituirlos.")
            print("   Aborto.")
            sys.exit(1)

    if args.reset:
        print("2️⃣  Borrando scorings anteriores al corte real...")
        if dry:
            print(f"   (dry-run, se borrarían {sinteticos_previos:,})")
        else:
            n = borrar_sinteticos(engine, fecha_inicio_real)
            print(f"   ✅ {n:,} scorings eliminados")
        print()

    # 3. Cargar referencias
    print("3️⃣  Cargando referencias...")
    umbrales = cargar_umbrales(engine)
    print(f"   Umbrales: P1≥{umbrales['P1_critica']:.2f}  P2≥{umbrales['P2_alta']:.2f}  P3≥{umbrales['P3_media']:.2f}")

    activos = cargar_activos(engine)
    print(f"   Activos activos: {len(activos):,}")

    ots_por_activo = cargar_ots_por_activo(engine, args.dias, fecha_inicio_real)
    total_ots = sum(len(ots) for ots in ots_por_activo.values())
    print(f"   OTs correctivas en ventana sintética: {total_ots:,} sobre {len(ots_por_activo):,} activos")
    print()

    # 4. Marcar OTs como TP o FN (decisión única por OT, balanceada al recall objetivo)
    print(f"4️⃣  Asignando TP/FN según recall objetivo ({args.recall:.2f})...")
    todas_ots = []
    for activo_id, ots in ots_por_activo.items():
        for ot in ots:
            todas_ots.append((activo_id, ot))
    random.shuffle(todas_ots)
    n_tp = int(round(total_ots * args.recall))
    for i, (_, ot) in enumerate(todas_ots):
        ot["sera_tp"] = (i < n_tp)
    print(f"   Marcadas TP: {n_tp:,}  |  marcadas FN: {total_ots - n_tp:,}")
    print()

    # 5. Generar scorings
    print("5️⃣  Generando scorings (esto puede tardar ~1 minuto)...")
    scorings = []
    contadores = {
        "ots_tp": n_tp, "ots_fn": total_ots - n_tp,
        "activos_con_ot": len(ots_por_activo),
        "activos_sin_ot": len(activos) - len(ots_por_activo),
    }
    n_dias = args.dias
    progress_cada = max(100, len(activos) // 20)

    for i, activo_id in enumerate(activos):
        if (i + 1) % progress_cada == 0:
            print(f"   {i+1:>5d}/{len(activos)}  ({(i+1)/len(activos)*100:.0f}%)")

        ots = ots_por_activo.get(activo_id, [])
        fecha = fecha_inicio

        while fecha <= fecha_fin:
            proxima_ot = encontrar_proxima_ot(ots, fecha)

            for horizonte in HORIZONTES:
                if proxima_ot is not None:
                    dias_a_falla = (proxima_ot["fecha_apertura"] - fecha).days
                    sera_tp = proxima_ot["sera_tp"]
                    prob = prob_pre_falla(dias_a_falla, horizonte, sera_tp)
                    sistema = None
                    if sera_tp and proxima_ot["sistemas"]:
                        sistema = random.choice(list(proxima_ot["sistemas"]))
                else:
                    prob = prob_rutinaria()
                    sistema = None

                prio = asignar_prioridad(prob, umbrales)

                scoring = {
                    "activo_id":          activo_id,
                    "fecha_scoring":      fecha,
                    "horizonte_dias":     horizonte,
                    "probabilidad_falla": round(prob, 4),
                    "prioridad":          prio,
                }
                if chk["tiene_sistema_en_riesgo"]:
                    scoring["sistema_en_riesgo"] = sistema
                if chk["tiene_modelo_version"]:
                    scoring["modelo_version"] = MODELO_VERSION
                if chk["tiene_prediccion"]:
                    scoring["prediccion"] = 1 if prio in ("P1_critica", "P2_alta") else 0

                scorings.append(scoring)

            fecha += timedelta(days=1)

    print(f"\n   ✅ {len(scorings):,} scorings generados")

    df_scoring = pd.DataFrame(scorings)

    # 6. Reporte
    reportar(df_scoring, contadores, umbrales)

    # 7. Persistencia
    if dry:
        print("⏸️  DRY RUN: no se insertó nada.")
        print("    Persistir: --commit")
        print("    Si hay sintéticos previos: --reset --commit\n")
        return

    print(f"6️⃣  Insertando {len(df_scoring):,} registros en chunks de {CHUNKSIZE_INSERT:,}...")
    df_scoring.to_sql(
        "scoring_resultados", engine,
        if_exists="append", index=False,
        chunksize=CHUNKSIZE_INSERT, method="multi"
    )
    print(f"   ✅ Inserción completa\n")

    print("✅ Listo. Próximos pasos:")
    print("    1. uv run python generar_feedback_sintetico.py --reset --commit")
    print("    2. uv run python -m src.scripts.calcular_paneles")
    print("    3. Recarga el dashboard.\n")


if __name__ == "__main__":
    main()
