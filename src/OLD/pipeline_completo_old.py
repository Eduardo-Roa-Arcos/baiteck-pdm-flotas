#!/usr/bin/env python3
"""
PIPELINE COMPLETO: Features → Parquet → Random Forest
Soluciona los problemas de feature_pipeline.py y ejecuta todo en orden.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from src.db import engine
from src.features.build_features import construir_features

# ============================================================
# PASO 1: GENERAR FEATURES
# ============================================================
print("\n" + "="*70)
print("🔄 PASO 1: GENERANDO FEATURES")
print("="*70)

def generar_features_multiples_fechas(dias_hacia_atras=180, paso=30, horizonte_dias=30):
    """Genera panel temporal para múltiples fechas"""
    
    hoy = pd.Timestamp.now().normalize()
    fechas = []
    
    # Generar fechas de corte
    for d in range(0, dias_hacia_atras, paso):
        fechas.append((hoy - timedelta(days=d)).strftime("%Y-%m-%d"))
    
    print(f"Generando features para {len(fechas)} fechas (paso={paso}d, horizonte={horizonte_dias}d)")
    
    paneles = []
    for i, fecha in enumerate(fechas, 1):
        try:
            print(f"  [{i:2d}/{len(fechas)}] {fecha}...", end=" ", flush=True)
            df = construir_features(fecha, horizonte_dias=horizonte_dias)
            paneles.append(df)
            print(f"✅ {len(df)} activos")
        except Exception as e:
            print(f"❌ {str(e)[:40]}")
    
    if not paneles:
        print("❌ No se generaron features")
        return None
    
    features = pd.concat(paneles, ignore_index=True)
    print(f"\n✅ Total: {len(features)} registros")
    
    return features

# Generar features
features_df = generar_features_multiples_fechas(dias_hacia_atras=180, paso=30, horizonte_dias=30)

if features_df is None:
    print("❌ Error: no se pudieron generar features")
    sys.exit(1)

# ============================================================
# PASO 2: GUARDAR EN SUPABASE
# ============================================================
print("\n" + "="*70)
print("💾 PASO 2: GUARDANDO EN SUPABASE")
print("="*70)

try:
    from sqlalchemy import text
    
    # Limpiar tabla
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE features_activo_fecha"))
        conn.commit()
    print("✅ Tabla limpiada")
    
    # Guardar
    features_df.to_sql(
        'features_activo_fecha',
        engine,
        if_exists='append',
        index=False,
        method='multi',
        chunksize=1000
    )
    print(f"✅ {len(features_df)} registros guardados en features_activo_fecha")
    
except Exception as e:
    print(f"❌ Error al guardar: {e}")
    sys.exit(1)

# ============================================================
# PASO 3: EXPORTAR A PARQUET
# ============================================================
print("\n" + "="*70)
print("📦 PASO 3: EXPORTANDO A PARQUET")
print("="*70)

os.makedirs('data/processed', exist_ok=True)

output_path = 'data/processed/panel_entrenamiento.parquet'
features_df.to_parquet(output_path, index=False)
print(f"✅ Exportado a: {output_path}")

# ============================================================
# PASO 4: VALIDACIÓN DE FEATURES
# ============================================================
print("\n" + "="*70)
print("✅ VALIDACIÓN DE FEATURES")
print("="*70)

print(f"\nDataset shape: {features_df.shape[0]} filas × {features_df.shape[1]} columnas")
print(f"Columnas: {list(features_df.columns)}")
print(f"\nDistribución del target:")
target_counts = features_df['target'].value_counts().sort_index()
for target_val, count in target_counts.items():
    pct = 100 * count / len(features_df)
    print(f"  target={target_val}: {count:5d} ({pct:5.1f}%)")

print(f"\nTasa de eventos: {features_df['target'].mean()*100:.2f}%")
print(f"Rango de fechas: {features_df['fecha_corte'].min()} a {features_df['fecha_corte'].max()}")
print(f"Activos únicos: {features_df['activo_id'].nunique()}")

# ============================================================
# PASO 5: ENTRENAR RANDOM FOREST
# ============================================================
print("\n" + "="*70)
print("🌲 PASO 5: ENTRENANDO RANDOM FOREST")
print("="*70)

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import (
    precision_score, recall_score, f1_score, 
    roc_auc_score, classification_report, confusion_matrix
)
import joblib

# Cargar el parquet que acabamos de crear
panel = pd.read_parquet(output_path)

print(f"\n1️⃣ Panel cargado: {panel.shape}")

# Identificar features
drop_cols = ["target", "activo_id", "fecha_corte", "horizonte_dias"]
feature_cols = [c for c in panel.columns if c not in drop_cols]

print(f"2️⃣ Features identificados: {len(feature_cols)}")
print(f"   {feature_cols}")

# Preparar datos
X = panel[feature_cols].fillna(-1)
y = panel["target"]

print(f"\n3️⃣ Datos preparados:")
print(f"   X: {X.shape}")
print(f"   y distribution: {y.value_counts().to_dict()}")

# Split temporal (70/30)
split_idx = int(len(panel) * 0.7)
X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

print(f"\n4️⃣ Split temporal (70/30):")
print(f"   Train: {X_train.shape[0]} (target={y_train.value_counts().to_dict()})")
print(f"   Test:  {X_test.shape[0]} (target={y_test.value_counts().to_dict()})")

# Entrenar
print(f"\n5️⃣ Entrenando Random Forest...")
rf = RandomForestClassifier(
    n_estimators=100,
    max_depth=12,
    min_samples_leaf=5,
    class_weight="balanced",
    n_jobs=-1,
    random_state=42
)
rf.fit(X_train, y_train)
print(f"   ✅ Modelo entrenado")

# Evaluar
print(f"\n6️⃣ Evaluando...")
y_pred = rf.predict(X_test)
y_pred_proba = rf.predict_proba(X_test)[:, 1]

# Calcular métricas
try:
    auc = roc_auc_score(y_test, y_pred_proba)
except:
    auc = 0.0

precision = precision_score(y_test, y_pred, zero_division=0)
recall = recall_score(y_test, y_pred, zero_division=0)
f1 = f1_score(y_test, y_pred, zero_division=0)

print(f"\n   MÉTRICAS:")
print(f"   AUC:       {auc:.4f}")
print(f"   Precision: {precision:.4f}")
print(f"   Recall:    {recall:.4f}")
print(f"   F1-Score:  {f1:.4f}")

print(f"\n   CLASSIFICATION REPORT:")
print(classification_report(y_test, y_pred))

# Guardar modelo
os.makedirs('models', exist_ok=True)
model_path = "models/modelo_rf_v1.0.joblib"
joblib.dump(rf, model_path)
print(f"\n7️⃣ Modelo guardado: {model_path}")

# ============================================================
# RESUMEN FINAL
# ============================================================
print("\n" + "="*70)
print("✅ PIPELINE COMPLETADO EXITOSAMENTE")
print("="*70)
print(f"\n📊 Resumen:")
print(f"  • Features generados: {len(features_df)} registros")
print(f"  • Guardados en Supabase: features_activo_fecha")
print(f"  • Parquet exportado: {output_path}")
print(f"  • Modelo Random Forest: {model_path}")
print(f"  • AUC en test: {auc:.4f}")
print(f"  • Próximo paso: ejecutar scoring_diario.py para predicciones")
print("\n" + "="*70 + "\n")
