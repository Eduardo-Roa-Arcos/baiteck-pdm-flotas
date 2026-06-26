# src/scripts/generar_feedback_sintetico.py
"""
Generación de registros sintéticos en feedback_taller usando LÓGICA INVERTIDA
adaptada a un modelo joven (pocos días en producción).

DOS UNIVERSOS DE FEEDBACK:

  Universo 1 — TP/FN desde OT correctivas reales
    Para cada OT correctiva real en los últimos N días, busca el último scoring
    del mismo activo dentro de los 30 días previos a la OT.
      • Última prioridad era P1/P2 → TP confirmada (modelo anticipó la falla)
      • Última prioridad era P3/P4 → FN documentado (modelo se le pasó)
      • Sin scoring previo del activo → omitir (no se puede medir)

    Sub-clasificación de TP según coincidencia de sistema:
      • sistema_match    → confirmada (TP fuerte)
      • sistema_mismatch → parcial    (alerta correcta, sistema distinto)
      • sin_clasificar   → confirmada con tag (OT sin eventos en taxonomía)

  Universo 2 — FP/Pendiente desde P1/P2 actuales NO capturadas en Universo 1
    Para cada P1/P2 viva que no fue ya marcada como TP en Universo 1:
      • edad > 2 días → 35% rechazada (con motivo) / 65% pendiente
      • edad ≤ 2 días → 5% rechazada / 95% pendiente
    Razonamiento: el taller no espera 30 días para revisar una alerta; cuando
    pasaron ≥3 días sin que se materialice nada, el taller ya inspeccionó.

POLÍTICA — falla_confirmada=TRUE SOLO cuando hay OT correctiva real (Universo 1).
Nunca se "inventan" confirmadas sin respaldo en ordenes_trabajo. Esto preserva
la honestidad de Vista 3.

USO:
    uv run python generar_feedback_sintetico.py                 # dry-run
    uv run python generar_feedback_sintetico.py --commit        # inserción real
    uv run python generar_feedback_sintetico.py --reset --commit  # sustituir previos
"""

import argparse
import random
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional, Dict, List, Tuple

import pandas as pd
from sqlalchemy import text

from src.db import engine


# ============================================================================
# CONFIGURACIÓN
# ============================================================================

VENTANA_OT_DIAS = 90              # OT correctivas observables hacia atrás
VENTANA_SCORING_PREVIO_DIAS = 30  # Para cada OT, buscar scoring previo en esta ventana
VENTANA_P1P2_DIAS = 90            # P1/P2 a considerar para Universo 2
EDAD_UMBRAL_REVISION = 2          # Días desde la alerta a partir de los cuales el taller probablemente revisó
SEMILLA_DEFAULT = 42

# Distribuciones del Universo 1 (cuando hay OT correctiva real)
DIST_SISTEMA_MATCH = {       # OT atendió el sistema pronosticado
    "confirmada": 0.85,
    "parcial":    0.10,
    "pendiente":  0.05,
}
DIST_SISTEMA_MISMATCH = {    # OT atendió sistemas distintos
    "parcial":    0.70,
    "confirmada": 0.20,
    "pendiente":  0.10,
}
DIST_SIN_CLASIFICAR = {      # OT sin eventos en taxonomía
    "confirmada": 0.70,
    "pendiente":  0.20,
    "parcial":    0.10,
}

# Distribuciones del Universo 2 (P1/P2 actuales, sin OT posterior dentro de su ventana)
DIST_P1P2_REVISADA = {       # edad > 2 días
    "rechazada":  0.35,
    "pendiente":  0.65,
}
DIST_P1P2_RECIENTE = {       # edad ≤ 2 días
    "rechazada":  0.05,
    "pendiente":  0.95,
}

# Top motivos de rechazo y pesos
MOTIVOS_RECHAZO = [
    ("Componente en buen estado",     0.40),
    ("Unidad recién intervenida",     0.25),
    ("Falla en otro sistema",         0.20),
    ("Alerta duplicada",              0.10),
    ("Otro motivo no especificado",   0.05),
]

# Tag para identificar registros sintéticos
TAG_SINTETICO = "[SINT]"


# ============================================================================
# VERIFICACIÓN DE ESQUEMA
# ============================================================================

def verificar_esquema(eng) -> Dict:
    sql = text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'feedback_taller';
    """)
    df = pd.read_sql(sql, eng)
    cols = set(df["column_name"].tolist())
    requeridas = {
        "scoring_id", "activo_id", "resultado_revision",
        "falla_confirmada", "falsa_alarma", "comentario_mecanico", "fecha_alerta",
    }
    return {
        "existe": len(cols) > 0,
        "requeridas_ok": requeridas.issubset(cols),
        "faltantes_req": list(requeridas - cols),
        "tiene_ot_id": "ot_id" in cols,
        "todas": cols,
    }


# ============================================================================
# CARGA DE DATOS REALES
# ============================================================================

def cargar_scoring_ventana(eng, dias_atras: int) -> pd.DataFrame:
    """Carga scoring del horizonte h30 (más representativo para feedback diario).
    h30 captura la señal con anticipación suficiente para el taller y evita 
    falsos negativos del h90 (curva lenta).
    """
    sql = text("""
        SELECT scoring_id, activo_id, fecha_scoring::date AS fecha_scoring,
               prioridad, sistema_en_riesgo, probabilidad_falla
        FROM scoring_resultados
        WHERE fecha_scoring >= CURRENT_DATE - (:dias || ' days')::interval
          AND horizonte_dias = 30
        ORDER BY activo_id, fecha_scoring;
    """)
    return pd.read_sql(sql, eng, params={"dias": dias_atras})

def cargar_ots_con_sistemas(eng, dias_atras: int) -> List[Dict]:
    """Trae OT correctivas + lista de sistemas afectados.
    Una OT puede tener N eventos = N sistemas distintos.
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
        ORDER BY ot.ot_id;
    """)
    df = pd.read_sql(sql, eng, params={"dias": dias_atras})

    ots_dict = {}
    for _, row in df.iterrows():
        ot_id = row["ot_id"]
        if ot_id not in ots_dict:
            ots_dict[ot_id] = {
                "ot_id":          ot_id,
                "activo_id":      row["activo_id"],
                "fecha_apertura": row["fecha_apertura"],
                "sistemas":       set(),
            }
        if row["sistema"]:
            ots_dict[ot_id]["sistemas"].add(row["sistema"])
    return list(ots_dict.values())


# ============================================================================
# INDEXACIÓN DE SCORING POR ACTIVO
# ============================================================================

def indexar_scoring_por_activo(df_scoring: pd.DataFrame) -> Dict[str, List[Dict]]:
    """Construye {activo_id: [scorings ordenados por fecha asc]} para búsqueda rápida."""
    index = defaultdict(list)
    for _, row in df_scoring.iterrows():
        index[row["activo_id"]].append({
            "scoring_id":         row["scoring_id"],
            "activo_id":          row["activo_id"],
            "fecha_scoring":      row["fecha_scoring"],
            "prioridad":          row["prioridad"],
            "sistema_en_riesgo":  row.get("sistema_en_riesgo"),
        })
    for activo_id in index:
        index[activo_id].sort(key=lambda r: r["fecha_scoring"])
    return index


def buscar_scoring_previo(activo_id: str, fecha_ot: date,
                          scoring_index: Dict, dias_ventana: int) -> Optional[Dict]:
    """Devuelve el scoring más reciente del activo en los `dias_ventana` previos a fecha_ot."""
    scorings = scoring_index.get(activo_id, [])
    fecha_min = fecha_ot - timedelta(days=dias_ventana)
    candidatos = [s for s in scorings if fecha_min <= s["fecha_scoring"] < fecha_ot]
    return candidatos[-1] if candidatos else None


# ============================================================================
# HELPERS DE GENERACIÓN
# ============================================================================

def elegir(distribucion: dict) -> str:
    estados = list(distribucion.keys())
    pesos = list(distribucion.values())
    return random.choices(estados, weights=pesos, k=1)[0]


def elegir_motivo_rechazo() -> str:
    motivos, pesos = zip(*MOTIVOS_RECHAZO)
    return random.choices(motivos, weights=pesos, k=1)[0]


def clasificar_tipo_match(sistema_pronosticado: Optional[str], sistemas_ot: set) -> str:
    if not sistemas_ot:
        return "sin_clasificar"
    sp = (sistema_pronosticado or "").lower().strip()
    if sp and sp in sistemas_ot:
        return "sistema_match"
    return "sistema_mismatch"


def comentario_tp(estado: str, tipo_match: str,
                  sistema_pronosticado: Optional[str], sistemas_ot: set) -> str:
    if estado == "confirmada":
        if tipo_match == "sistema_match":
            return f"{TAG_SINTETICO} Falla confirmada en {sistema_pronosticado}"
        if tipo_match == "sin_clasificar":
            return f"{TAG_SINTETICO} Falla confirmada (OT pendiente de clasificación taxonómica)"
        sis = ", ".join(sorted(sistemas_ot)) if sistemas_ot else "otro"
        return f"{TAG_SINTETICO} Falla confirmada en sistemas alternos: {sis}"
    if estado == "parcial":
        sis = ", ".join(sorted(sistemas_ot)) if sistemas_ot else "otro sistema"
        return f"{TAG_SINTETICO} Síntoma detectado pero falla afectó: {sis}"
    return f"{TAG_SINTETICO} Pendiente de revisión"


# ============================================================================
# GENERADORES DE REGISTRO
# ============================================================================

def generar_tp(scoring_previo: Dict, ot: Dict) -> Dict:
    """Universo 1, scoring previo P1/P2 → TP candidato. Sub-tipo por match de sistema."""
    tipo_match = clasificar_tipo_match(scoring_previo["sistema_en_riesgo"], ot["sistemas"])
    if tipo_match == "sistema_match":
        distrib = DIST_SISTEMA_MATCH
    elif tipo_match == "sistema_mismatch":
        distrib = DIST_SISTEMA_MISMATCH
    else:
        distrib = DIST_SIN_CLASIFICAR
    estado = elegir(distrib)

    if estado == "confirmada" or estado == "parcial":
        falla, falsa = True, False
    else:
        falla, falsa = False, False

    return {
        "scoring_id":          scoring_previo["scoring_id"],
        "activo_id":           scoring_previo["activo_id"],
        "fecha_alerta":        scoring_previo["fecha_scoring"],
        "resultado_revision":  estado,
        "falla_confirmada":    falla,
        "falsa_alarma":        falsa,
        "comentario_mecanico": comentario_tp(estado, tipo_match,
                                              scoring_previo["sistema_en_riesgo"],
                                              ot["sistemas"]),
        "ot_id":               ot["ot_id"] if estado in ("confirmada", "parcial") else None,
        "_origen":             f"TP_{tipo_match}",
    }


def generar_fn(scoring_previo: Dict, ot: Dict) -> Dict:
    """Universo 1, scoring previo P3/P4 → FN documentado."""
    sistema_pron = scoring_previo.get("sistema_en_riesgo") or "no pronosticado"
    sistemas_ot = ", ".join(sorted(ot["sistemas"])) if ot["sistemas"] else "no clasificada aún"
    return {
        "scoring_id":          scoring_previo["scoring_id"],
        "activo_id":           scoring_previo["activo_id"],
        "fecha_alerta":        scoring_previo["fecha_scoring"],
        "resultado_revision":  "confirmada",
        "falla_confirmada":    True,
        "falsa_alarma":        False,
        "comentario_mecanico": f"{TAG_SINTETICO} Falla ocurrida sin alerta previa (FN). Pronosticado: {sistema_pron}; OT atendió: {sistemas_ot}",
        "ot_id":               ot["ot_id"],
        "_origen":             "FN_modelo",
    }


def generar_fp_o_pendiente(scoring: Dict, edad_dias: int) -> Dict:
    """Universo 2, P1/P2 sin OT posterior dentro de su ventana actual."""
    distrib = DIST_P1P2_REVISADA if edad_dias > EDAD_UMBRAL_REVISION else DIST_P1P2_RECIENTE
    estado = elegir(distrib)

    if estado == "rechazada":
        motivo = elegir_motivo_rechazo()
        comentario = f"{TAG_SINTETICO} {motivo}"
        falla, falsa = False, True
    else:
        comentario = f"{TAG_SINTETICO} Pendiente de revisión"
        falla, falsa = False, False

    return {
        "scoring_id":          scoring["scoring_id"],
        "activo_id":           scoring["activo_id"],
        "fecha_alerta":        scoring["fecha_scoring"],
        "resultado_revision":  estado,
        "falla_confirmada":    falla,
        "falsa_alarma":        falsa,
        "comentario_mecanico": comentario,
        "ot_id":               None,
        "_origen":             "FP_revisada" if estado == "rechazada" else "pendiente",
    }


# ============================================================================
# REPORTE
# ============================================================================

def reportar(df_fb: pd.DataFrame, contadores: Dict):
    print("\n" + "=" * 72)
    print(" RESULTADO POR ORIGEN")
    print("=" * 72)
    origen_count = df_fb["_origen"].value_counts()
    for origen, n in origen_count.items():
        print(f"    {origen:25s}  {n}")

    print("\n" + "-" * 72)
    print(" DISTRIBUCIÓN FINAL POR resultado_revision")
    print("-" * 72)
    dist = df_fb["resultado_revision"].value_counts()
    for estado, n in dist.items():
        pct = n / len(df_fb) * 100
        print(f"    {estado:12s}  {n:>4d}  ({pct:.1f}%)")

    con_ot = df_fb["ot_id"].notna().sum()
    print(f"\n    Registros con ot_id (vinculados a OT real): {con_ot}/{len(df_fb)}")

    # Top motivos de rechazo
    rech = df_fb[df_fb["falsa_alarma"] == True]
    if len(rech):
        print("\n  Top motivos de rechazo:")
        motivos = (rech["comentario_mecanico"]
                   .str.replace(f"{TAG_SINTETICO} ", "", regex=False)
                   .value_counts())
        for m, n in motivos.items():
            print(f"    {m:40s}  {n}")

    # Matriz de confusión basada en falla_confirmada
    print("\n" + "-" * 72)
    print(" MATRIZ DE CONFUSIÓN RESULTANTE")
    print("-" * 72)
    tp = (df_fb["_origen"].str.startswith("TP_")).sum()
    tp_confirmadas = ((df_fb["_origen"].str.startswith("TP_")) &
                      (df_fb["falla_confirmada"] == True)).sum()
    fn = (df_fb["_origen"] == "FN_modelo").sum()
    fp = (df_fb["_origen"] == "FP_revisada").sum()
    pend = (df_fb["_origen"] == "pendiente").sum()

    print(f"                  Alertamos    No alertamos")
    print(f"  Falla real        TP={tp_confirmadas:>4d}        FN={fn:>4d}")
    print(f"  No falla          FP={fp:>4d}        TN=(no documentado)")
    print(f"                                       (P3/P4 sin OT real no se inserta)")
    print(f"  Pendientes (ventana abierta): {pend}")

    if tp_confirmadas + fn > 0:
        recall = tp_confirmadas / (tp_confirmadas + fn)
        print(f"\n  Recall    = {recall:.3f}   →   {recall*10:.1f}/10 fallas reales fueron alertadas")
    if tp_confirmadas + fp > 0:
        prec = tp_confirmadas / (tp_confirmadas + fp)
        print(f"  Precision = {prec:.3f}   →   {prec*10:.1f}/10 alertas eran fallas reales")
    print()


# ============================================================================
# PERSISTENCIA
# ============================================================================

def insertar_feedback(eng, df_fb: pd.DataFrame, tiene_ot_id: bool):
    columnas = [
        "scoring_id", "activo_id", "fecha_alerta",
        "resultado_revision", "falla_confirmada", "falsa_alarma",
        "comentario_mecanico",
    ]
    if tiene_ot_id:
        columnas.append("ot_id")
    df_out = df_fb[columnas].copy()
    df_out.to_sql("feedback_taller", eng, if_exists="append",
                  index=False, chunksize=200, method="multi")
    print(f"   ✅ {len(df_out)} registros insertados en feedback_taller")


def borrar_feedback_sintetico(eng) -> int:
    sql = text("""
        DELETE FROM feedback_taller WHERE comentario_mecanico LIKE :tag;
    """)
    with eng.begin() as conn:
        result = conn.execute(sql, {"tag": f"{TAG_SINTETICO}%"})
        return result.rowcount


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--commit", action="store_true",
                        help="Inserta realmente en la BD (default: dry-run)")
    parser.add_argument("--reset", action="store_true",
                        help="Elimina feedback sintético previo antes de generar")
    parser.add_argument("--seed", type=int, default=SEMILLA_DEFAULT)
    parser.add_argument("--ventana-ot", type=int, default=VENTANA_OT_DIAS,
                        help=f"Días hacia atrás para OT correctivas (default: {VENTANA_OT_DIAS})")
    args = parser.parse_args()

    random.seed(args.seed)
    dry = not args.commit

    print("=" * 72)
    print(" GENERACIÓN DE FEEDBACK SINTÉTICO — feedback_taller")
    print(" (Lógica invertida: doble universo TP/FN + FP/Pendiente)")
    print("=" * 72)
    print(f" Modo:       {'DRY RUN' if dry else 'COMMIT'}")
    print(f" Ventana OT: últimos {args.ventana_ot} días")
    print(f" Semilla:    {args.seed}")
    print()

    # 0. Verificar esquema
    print("0️⃣  Verificando esquema...")
    chk = verificar_esquema(engine)
    if not chk["existe"] or not chk["requeridas_ok"]:
        print(f"   ❌ Esquema inválido: {chk}")
        sys.exit(1)
    print(f"   ✅ Esquema OK (ot_id: {'sí' if chk['tiene_ot_id'] else 'no'})")
    print()

    # 1. Reset si corresponde
    if args.reset:
        print("1️⃣  Borrando feedback sintético previo...")
        if dry:
            print("   (dry-run, no se borra)")
        else:
            n = borrar_feedback_sintetico(engine)
            print(f"   ✅ {n} registros sintéticos eliminados")
        print()

    # 2. Cargar datos reales
    print("2️⃣  Cargando datos reales...")
    df_scoring = cargar_scoring_ventana(engine, args.ventana_ot + VENTANA_SCORING_PREVIO_DIAS)
    print(f"   • {len(df_scoring)} scorings cargados")
    print(f"     Rango: {df_scoring['fecha_scoring'].min()} → {df_scoring['fecha_scoring'].max()}")
    p1p2_total = df_scoring["prioridad"].isin(["P1_critica", "P2_alta"]).sum()
    print(f"     P1/P2: {p1p2_total} | P3/P4: {len(df_scoring) - p1p2_total}")

    ots_list = cargar_ots_con_sistemas(engine, args.ventana_ot)
    con_clasif = sum(1 for o in ots_list if o["sistemas"])
    print(f"\n   • {len(ots_list)} OT correctivas en los últimos {args.ventana_ot} días")
    print(f"     - Con eventos clasificados: {con_clasif}")
    print(f"     - Sin clasificar todavía:   {len(ots_list) - con_clasif}")

    scoring_index = indexar_scoring_por_activo(df_scoring)
    print(f"\n   • Índice de scoring construido: {len(scoring_index)} activos únicos")
    print()

    # 3. UNIVERSO 1 — TP/FN desde OT correctivas reales
    print("3️⃣  Universo 1: TP/FN desde OT correctivas reales...")
    feedbacks = []
    scoring_ids_usados = set()
    contadores = defaultdict(int)

    for ot in ots_list:
        scoring_previo = buscar_scoring_previo(
            ot["activo_id"], ot["fecha_apertura"],
            scoring_index, VENTANA_SCORING_PREVIO_DIAS
        )
        if scoring_previo is None:
            contadores["ot_sin_scoring_previo"] += 1
            continue

        scoring_ids_usados.add(scoring_previo["scoring_id"])
        es_alerta = scoring_previo["prioridad"] in ("P1_critica", "P2_alta")

        if es_alerta:
            feedbacks.append(generar_tp(scoring_previo, ot))
            contadores["tp_generados"] += 1
        else:
            feedbacks.append(generar_fn(scoring_previo, ot))
            contadores["fn_generados"] += 1

    print(f"   • TP candidatos generados: {contadores['tp_generados']}")
    print(f"   • FN documentados:         {contadores['fn_generados']}")
    print(f"   • OT sin scoring previo:   {contadores['ot_sin_scoring_previo']}")
    print()

    # 4. UNIVERSO 2 — FP/Pendiente desde P1/P2 no capturadas
    print("4️⃣  Universo 2: FP/Pendiente desde P1/P2 reales (no sintéticas)...")
    hoy = date.today()

    # Detectar la frontera entre scoring real y scoring sintético
    sql_frontera = text("""
        SELECT MIN(fecha_scoring::date) AS primer_real
        FROM scoring_resultados
        WHERE fecha_scoring >= CURRENT_DATE - INTERVAL '14 days';
    """)
    fecha_inicio_real = pd.read_sql(sql_frontera, engine).iloc[0]["primer_real"]
    print(f"   Procesando solo P1/P2 con fecha_scoring >= {fecha_inicio_real}")

    df_p1p2 = df_scoring[
        (df_scoring["prioridad"].isin(["P1_critica", "P2_alta"])) &
        (df_scoring["fecha_scoring"] >= fecha_inicio_real)
    ]
    n_revisada = n_reciente = 0

    for _, row in df_p1p2.iterrows():
        if row["scoring_id"] in scoring_ids_usados:
            continue
        edad_dias = (hoy - row["fecha_scoring"]).days
        feedbacks.append(generar_fp_o_pendiente(
            {"scoring_id": row["scoring_id"],
             "activo_id":  row["activo_id"],
             "fecha_scoring": row["fecha_scoring"]},
            edad_dias
        ))
        if edad_dias > EDAD_UMBRAL_REVISION:
            n_revisada += 1
        else:
            n_reciente += 1

    print(f"   • P1/P2 con edad > {EDAD_UMBRAL_REVISION}d (taller pudo revisar): {n_revisada}")
    print(f"   • P1/P2 con edad ≤ {EDAD_UMBRAL_REVISION}d (recientes):           {n_reciente}")
    print(f"   • Total Universo 2: {n_revisada + n_reciente}")
    print()

    df_fb = pd.DataFrame(feedbacks)
    print(f"   Total feedback generado: {len(df_fb)}")

    # 5. Reporte
    reportar(df_fb, contadores)

    # 6. Persistencia
    if dry:
        print("⏸️  DRY RUN: no se insertó nada.")
        print("    Persistir: --commit")
        print("    Sustituir feedback sintético previo: --reset --commit\n")
        return

    print("5️⃣  Insertando en feedback_taller...")
    insertar_feedback(engine, df_fb, chk["tiene_ot_id"])
    print("\n✅ Listo. Próximos pasos:")
    print("    1. uv run python -m src.scripts.calcular_paneles")
    print("    2. Recarga el dashboard.\n")


if __name__ == "__main__":
    main()
