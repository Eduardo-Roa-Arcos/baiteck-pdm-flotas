import pandas as pd
import numpy as np
from src.db import engine

def auditar_ots() -> dict:
    """Audita la calidad de datos en ordenes_trabajo"""
    ots = pd.read_sql("SELECT * FROM ordenes_trabajo", engine)
    n = len(ots)

    if n == 0:
        return {"error": "No hay ordenes de trabajo cargadas"}

    metricas = {"total_registros": int(n)}

    # Completitud de campos críticos
    campos = ["activo_id", "fecha_apertura", "tipo_ot"]
    metricas["completitud"] = {
        c: round(float(100 * ots[c].notna().sum() / n), 2) 
        for c in campos if c in ots.columns
    }

    # Validación de fechas
    if "fecha_apertura" in ots.columns and "fecha_cierre" in ots.columns:
        ots["fecha_apertura"] = pd.to_datetime(ots["fecha_apertura"], errors="coerce")
        ots["fecha_cierre"] = pd.to_datetime(ots["fecha_cierre"], errors="coerce")
        invalidas = ots["fecha_cierre"] < ots["fecha_apertura"]
        metricas["fechas_invalidas_pct"] = round(float(100 * invalidas.sum() / n), 2)

    # Detección de duplicados
    if "ot_id" in ots.columns:
        metricas["duplicados_pct"] = round(float(100 * ots["ot_id"].duplicated().sum() / n), 2)

    return metricas

def auditar_activos() -> dict:
    """Audita la calidad de datos en activos"""
    activos = pd.read_sql("SELECT * FROM activos", engine)
    n = len(activos)

    if n == 0:
        return {"error": "No hay activos cargados"}

    metricas = {"total_registros": int(n)}

    # Completitud de campos críticos
    campos = ["patente", "marca", "modelo", "anio_fabricacion"]
    metricas["completitud"] = {
        c: round(float(100 * activos[c].notna().sum() / n), 2)
        for c in campos if c in activos.columns
    }

    # Duplicados de patente
    if "patente" in activos.columns:
        metricas["patentes_duplicadas_pct"] = round(float(100 * activos["patente"].duplicated().sum() / n), 2)

    return metricas

def auditar_repuestos() -> dict:
    """Audita la calidad de datos en repuestos_consumidos"""
    repuestos = pd.read_sql("SELECT * FROM repuestos_consumidos", engine)
    n = len(repuestos)

    if n == 0:
        return {"error": "No hay repuestos cargados"}

    metricas = {"total_registros": int(n)}

    # Completitud
    campos = ["ot_id", "sku", "cantidad", "costo_unitario_clp"]
    metricas["completitud"] = {
        c: round(float(100 * repuestos[c].notna().sum() / n), 2)
        for c in campos if c in repuestos.columns
    }

    # Valores negativos
    if "cantidad" in repuestos.columns:
        metricas["cantidad_negativa_pct"] = round(float(100 * (repuestos["cantidad"] < 0).sum() / n), 2)

    if "costo_unitario_clp" in repuestos.columns:
        metricas["costo_negativo_pct"] = round(float(100 * (repuestos["costo_unitario_clp"] < 0).sum() / n), 2)

    return metricas

def reporte_auditoria():
    """Genera reporte completo de calidad de datos"""
    print("\n" + "="*60)
    print("📊 REPORTE DE AUDITORÍA DE CALIDAD DE DATOS")
    print("="*60 + "\n")

    print("🚗 ACTIVOS:")
    audit_activos = auditar_activos()
    for key, value in audit_activos.items():
        print(f"  {key}: {value}")

    print("\n📋 ÓRDENES DE TRABAJO:")
    audit_ots = auditar_ots()
    for key, value in audit_ots.items():
        print(f"  {key}: {value}")

    print("\n🔧 REPUESTOS CONSUMIDOS:")
    audit_repuestos = auditar_repuestos()
    for key, value in audit_repuestos.items():
        print(f"  {key}: {value}")

    print("\n" + "="*60 + "\n")

    return {
        "activos": audit_activos,
        "ordenes_trabajo": audit_ots,
        "repuestos": audit_repuestos
    }

if __name__ == "__main__":
    reporte_auditoria()
