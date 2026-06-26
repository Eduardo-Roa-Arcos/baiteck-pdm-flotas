#!/usr/bin/env python3
"""
disponibilidad_utils.py
=======================

Lógica compartida de cálculo de disponibilidad diaria, usada por:
  - crear_disponibilidad_diaria_FULL.py
  - crear_disponibilidad_diaria_INCREMENTAL.py

Mejora respecto a la versión heurística anterior (correctiva=8h fija, preventiva=4h fija):

  1. DOWNTIME REAL: cuando la OT tiene fecha_cierre, se calcula el tiempo detenido
     real (intervalo apertura→cierre) y se distribuye hora a hora entre los días
     que abarca. Una reparación de 3 días deja de contarse como 8h en un solo día.

  2. SEVERIDAD (ot_falla_evento): cuando NO hay fecha_cierre (OT abierta o dato
     ausente), el fallback ya no es un valor fijo: se pondera por la severidad
     real del evento de falla (critica > media > leve). Aquí entra la nueva
     estructura de taxonomía al cálculo operacional.

  3. fuente: cada fila queda marcada como 'calculado' (downtime real) o
     'inferido' (fallback heurístico), alineado con la columna `fuente` de la
     tabla disponibilidad_diaria.

Clasificación planificado vs. no planificado:
  - preventiva / preventivo / mantenimiento  → detenido PLANIFICADO
  - correctiva / correctivo / emergency       → detenido NO PLANIFICADO
  - otro                                       → no planificado (conservador)
"""

from datetime import timedelta
from typing import Optional

import pandas as pd

TIPOS_PREVENTIVOS = {"preventiva", "preventivo", "mantenimiento"}
TIPOS_CORRECTIVOS = {"correctiva", "correctivo", "emergency"}

# Horas de fallback por severidad cuando NO hay fecha_cierre utilizable.
HORAS_FALLBACK_SEVERIDAD = {
    "critica": 24,
    "crítica": 24,
    "media": 8,
    "leve": 4,
}
# Fallback por tipo cuando no hay severidad ni cierre.
HORAS_FALLBACK_TIPO = {"correctiva": 8, "preventiva": 4}


def _es_planificado(tipo_ot_lower: str) -> bool:
    return tipo_ot_lower in TIPOS_PREVENTIVOS


def _horas_fallback(tipo_ot_lower: str, severidad: Optional[str]) -> float:
    """Horas estimadas cuando no se puede usar el intervalo real."""
    if severidad:
        s = str(severidad).strip().lower()
        if s in HORAS_FALLBACK_SEVERIDAD:
            return HORAS_FALLBACK_SEVERIDAD[s]
    if tipo_ot_lower in TIPOS_PREVENTIVOS:
        return HORAS_FALLBACK_TIPO["preventiva"]
    return HORAS_FALLBACK_TIPO["correctiva"]


def calcular_disponibilidad(ots: pd.DataFrame,
                            activos_ids,
                            fecha_inicio,
                            hoy) -> pd.DataFrame:
    """
    Calcula disponibilidad diaria por activo en el rango [fecha_inicio, hoy].

    Args:
        ots: DataFrame de ordenes_trabajo con AL MENOS las columnas:
             activo_id, fecha_apertura (datetime), fecha_cierre (datetime/NaT),
             tipo_ot_lower (str). Opcional: severidad (str) para el fallback.
        activos_ids: iterable de activo_id a procesar.
        fecha_inicio: date — primer día del rango (inclusive).
        hoy: date — último día del rango (inclusive).

    Returns:
        DataFrame con columnas:
        activo_id, fecha, horas_operativas, horas_detenido_planificado,
        horas_detenido_no_planificado, fuente
    """
    if "severidad" not in ots.columns:
        ots = ots.copy()
        ots["severidad"] = None

    # Acumulador: (activo_id, date) -> dict con horas y origen
    acc = {}

    def _add(activo_id, dia, plan_h, noplan_h, calculado: bool):
        key = (activo_id, dia)
        if key not in acc:
            acc[key] = {"plan": 0.0, "noplan": 0.0, "calculado": False}
        acc[key]["plan"] += plan_h
        acc[key]["noplan"] += noplan_h
        acc[key]["calculado"] = acc[key]["calculado"] or calculado

    activos_set = set(activos_ids)

    for row in ots.itertuples(index=False):
        activo_id = getattr(row, "activo_id")
        if activo_id not in activos_set:
            continue

        apertura = getattr(row, "fecha_apertura")
        cierre = getattr(row, "fecha_cierre")
        tipo_lower = (getattr(row, "tipo_ot_lower") or "")
        severidad = getattr(row, "severidad", None)
        planificado = _es_planificado(tipo_lower)

        if pd.isna(apertura):
            continue
        apertura = pd.Timestamp(apertura)

        usar_real = pd.notna(cierre) and pd.Timestamp(cierre) > apertura

        if usar_real:
            cierre = pd.Timestamp(cierre)
            # Distribuir el intervalo [apertura, cierre] hora a hora por día.
            dia = apertura.normalize()
            fin = cierre.normalize()
            while dia <= fin:
                ini_dia = dia
                fin_dia = dia + timedelta(days=1)
                solape_ini = max(apertura, ini_dia)
                solape_fin = min(cierre, fin_dia)
                horas = (solape_fin - solape_ini).total_seconds() / 3600.0
                horas = max(0.0, min(horas, 24.0))
                if horas > 0:
                    d = dia.date()
                    if planificado:
                        _add(activo_id, d, horas, 0.0, calculado=True)
                    else:
                        _add(activo_id, d, 0.0, horas, calculado=True)
                dia += timedelta(days=1)
        else:
            # Fallback ponderado por severidad, en el día de apertura.
            horas = _horas_fallback(tipo_lower, severidad)
            d = apertura.date()
            if planificado:
                _add(activo_id, d, horas, 0.0, calculado=False)
            else:
                _add(activo_id, d, 0.0, horas, calculado=False)

    # Construir matriz completa: todos los activos × todos los días del rango.
    filas = []
    n_dias = (hoy - fecha_inicio).days
    for activo_id in activos_set:
        for offset in range(n_dias + 1):
            d = fecha_inicio + timedelta(days=offset)
            datos = acc.get((activo_id, d))
            if datos:
                plan = min(datos["plan"], 24.0)
                noplan = min(datos["noplan"], 24.0 - plan)
                fuente = "calculado" if datos["calculado"] else "inferido"
            else:
                plan, noplan, fuente = 0.0, 0.0, "calculado"
            operativas = max(0.0, 24.0 - (plan + noplan))
            filas.append({
                "activo_id": activo_id,
                "fecha": d,
                "horas_operativas": round(operativas, 2),
                "horas_detenido_planificado": round(plan, 2),
                "horas_detenido_no_planificado": round(noplan, 2),
                "fuente": fuente,
            })

    return pd.DataFrame(filas)


def cargar_severidad_por_ot(engine) -> pd.DataFrame:
    """
    Devuelve, por ot_id, la severidad máxima registrada en ot_falla_evento.
    Orden de severidad: critica > media > leve. Sirve para ponderar el fallback.
    Si la tabla está vacía o no existe, devuelve DataFrame vacío.
    """
    try:
        df = pd.read_sql(
            "SELECT ot_id, severidad FROM ot_falla_evento WHERE ot_id IS NOT NULL",
            engine,
        )
    except Exception:
        return pd.DataFrame(columns=["ot_id", "severidad"])

    if df.empty:
        return pd.DataFrame(columns=["ot_id", "severidad"])

    rank = {"critica": 3, "crítica": 3, "media": 2, "leve": 1}
    df["_r"] = df["severidad"].astype(str).str.lower().map(rank).fillna(0)
    df = df.sort_values("_r", ascending=False).drop_duplicates("ot_id", keep="first")
    return df[["ot_id", "severidad"]]
