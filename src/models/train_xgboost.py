# src/models/train_xgboost.py
# VERSIÓN MEJORADA: Entrena modelos separados para cada horizonte
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import pandas as pd
import numpy as np
import joblib
import json
from datetime import datetime
import xgboost as xgb
from sklearn.metrics import (
    precision_score, recall_score, f1_score, 
    roc_auc_score, classification_report, confusion_matrix,
    precision_recall_curve
)

# NUEVO: Horizontes a entrenar
HORIZONTES_ENTRENAMIENTO = [7, 30, 90]

def temporal_split(df: pd.DataFrame, test_size: float = 0.3):
    """Split temporal: 70% train, 30% test"""
    split_idx = int(len(df) * (1 - test_size))
    train = df.iloc[:split_idx].copy()
    test = df.iloc[split_idx:].copy()
    return train, test

def encontrar_mejor_threshold(y_test, y_pred_proba, target_recall=0.70):
    """
    Encuentra el mejor threshold que maximice F1 manteniendo un recall mínimo.
    Por defecto, busca 70% de recall (detectar 70% de las fallas reales).
    """
    precisions, recalls, thresholds = precision_recall_curve(y_test, y_pred_proba)
    
    # Encontrar threshold que cumpla con recall target
    indices_validos = np.where(recalls >= target_recall)[0]
    
    if len(indices_validos) == 0:
        # Si no alcanza el recall target, usar el que da máximo F1
        f1_scores = 2 * (precisions[:-1] * recalls[:-1]) / (precisions[:-1] + recalls[:-1] + 1e-10)
        idx_mejor = np.argmax(f1_scores)
        threshold_optimo = thresholds[idx_mejor]
    else:
        # Entre los que cumplen recall, usar el que maximiza precision
        idx_mejor = np.argmax(precisions[indices_validos])
        threshold_optimo = thresholds[indices_validos[idx_mejor]]
    
    return threshold_optimo

def entrenar_horizonte(panel: pd.DataFrame, horizonte: int, version: str = "v1.0"):
    """
    Entrena un modelo XGBoost para un horizonte específico.
    
    Args:
        panel: DataFrame con panel_entrenamiento
        horizonte: Número de días (7, 30 o 90)
        version: Versión del modelo
    
    Returns:
        bool: True si fue exitoso
    """
    print(f"\n{'='*70}")
    print(f"⚡ ENTRENAMIENTO XGBOOST - HORIZONTE {horizonte} DÍAS")
    print(f"{'='*70}\n")

    # 1. FILTRAR POR HORIZONTE
    print(f"1️⃣  Filtrando datos para horizonte {horizonte}...")
    panel_horizonte = panel[panel["horizonte_dias"] == horizonte].copy()
    
    if len(panel_horizonte) == 0:
        print(f"   ❌ No hay datos para horizonte {horizonte}")
        return False
    
    print(f"   ✅ {len(panel_horizonte)} registros para horizonte {horizonte}\n")

    # 2. FEATURES
    print("2️⃣  Identificando features...")
    # CAMBIO: No descartamos horizonte_dias aquí, ya lo filtramos arriba
    drop_cols = ["target", "activo_id", "fecha_corte", "horizonte_dias",
                 "patente", "marca", "modelo", "tipo_vehiculo", "fecha_alta_flota"]
    feature_cols = [c for c in panel_horizonte.columns if c not in drop_cols]
    print(f"   ✅ {len(feature_cols)} features\n")

    # 3. SPLIT TEMPORAL
    print("3️⃣  Split temporal (70/30)...")
    train, test = temporal_split(panel_horizonte, test_size=0.3)
    
    train_target_counts = train["target"].value_counts().sort_index()
    test_target_counts = test["target"].value_counts().sort_index()
    
    print(f"   Train: {len(train)} registros")
    for target_val, count in train_target_counts.items():
        pct = 100 * count / len(train)
        print(f"      target={target_val}: {count} ({pct:.1f}%)")
    
    print(f"   Test: {len(test)} registros")
    for target_val, count in test_target_counts.items():
        pct = 100 * count / len(test)
        print(f"      target={target_val}: {count} ({pct:.1f}%)")
    print()

    # 4. PREPARAR DATOS
    print("4️⃣  Preparando features...")
    X_train = train[feature_cols].fillna(-1)
    y_train = train["target"]
    X_test = test[feature_cols].fillna(-1)
    y_test = test["target"]
    print(f"   X_train: {X_train.shape} | X_test: {X_test.shape}\n")
    # RENOMBRAR COLUMNAS A NOMBRES CORTOS ANTES DE ENTRENAR
    # Mapeo: nombres largos → nombres cortos
    mapeo_renombramiento = {}
    for col in X_train.columns:
        if col.startswith('count_ot_'):
            dias = col.split('_')[-1]  # Extrae "7d", "30d", "90d"
            mapeo_renombramiento[col] = f'ot_{dias}'
        elif col.startswith('count_correctivas_'):
            dias = col.split('_')[-1]
            mapeo_renombramiento[col] = f'corr_{dias}'
        elif col.startswith('costo_total_'):
            dias = col.split('_')[-1]
            mapeo_renombramiento[col] = f'costo_{dias}'
        elif col.startswith('mtbf_'):
            # mtbf_90d → mtbf_90d (sin cambio)
            mapeo_renombramiento[col] = col
    
    X_train = X_train.rename(columns=mapeo_renombramiento)
    X_test = X_test.rename(columns=mapeo_renombramiento)
    feature_cols = X_train.columns.tolist()

    # 5. ENTRENAR
    print("5️⃣  Entrenando XGBoost...")
    
    scale_pos_weight = (y_train == 0).sum() / max(1, (y_train == 1).sum())
    
    print(f"   Parámetros:")
    print(f"   • n_estimators=200")
    print(f"   • max_depth=5")
    print(f"   • learning_rate=0.1")
    print(f"   • scale_pos_weight={scale_pos_weight:.2f}\n")
    
    xgb_model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        verbosity=0,
        eval_metric='logloss'
    )
    
    xgb_model.fit(X_train, y_train)
    print(f"   ✅ Modelo entrenado\n")

    # 6. PREDICCIONES
    print("6️⃣  Generando predicciones...")
    y_pred_default = xgb_model.predict(X_test)
    y_pred_proba = xgb_model.predict_proba(X_test)[:, 1]
    
    print(f"   Probabilidades: min={y_pred_proba.min():.4f}, max={y_pred_proba.max():.4f}")
    print(f"   Media: {y_pred_proba.mean():.4f}\n")

    # 7. THRESHOLD OPTIMO
    print("7️⃣  Optimizando threshold...")
    threshold_optimo = encontrar_mejor_threshold(y_test, y_pred_proba, target_recall=0.70)
    y_pred_optimizado = (y_pred_proba >= threshold_optimo).astype(int)
    
    print(f"   Threshold óptimo: {threshold_optimo:.4f}\n")

    # 8. EVALUAR
    print("8️⃣  Evaluando modelo...\n")
    
    print("📊 RENDIMIENTO CON THRESHOLD = 0.5000:")
    print("-" * 70)
    
    auc_default = roc_auc_score(y_test, y_pred_proba)
    precision_default = precision_score(y_test, y_pred_default, zero_division=0)
    recall_default = recall_score(y_test, y_pred_default, zero_division=0)
    f1_default = f1_score(y_test, y_pred_default, zero_division=0)
    
    print(f"AUC:       {auc_default:.4f}")
    print(f"Precision: {precision_default:.4f}")
    print(f"Recall:    {recall_default:.4f}")
    print(f"F1-Score:  {f1_default:.4f}\n")
    
    print("📊 RENDIMIENTO CON THRESHOLD = {:.4f}:\n".format(threshold_optimo))
    print("-" * 70)
    
    auc_optimo = roc_auc_score(y_test, y_pred_proba)
    precision_optimo = precision_score(y_test, y_pred_optimizado, zero_division=0)
    recall_optimo = recall_score(y_test, y_pred_optimizado, zero_division=0)
    f1_optimo = f1_score(y_test, y_pred_optimizado, zero_division=0)
    
    print(f"AUC:       {auc_optimo:.4f}")
    print(f"Precision: {precision_optimo:.4f}")
    print(f"Recall:    {recall_optimo:.4f}")
    print(f"F1-Score:  {f1_optimo:.4f}\n")

    # 9. FEATURE IMPORTANCE
    print("9️⃣  Feature Importance (top 10):")
    print("-" * 70)
    feature_importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': xgb_model.feature_importances_
    }).sort_values('importance', ascending=False)
    
    for idx, row in feature_importance.head(10).iterrows():
        bar_length = int(row['importance'] * 50)
        bar = "█" * bar_length
        print(f"{row['feature']:30s} {bar} {row['importance']:.4f}")
    print()

    # 10. GUARDAR ARTEFACTOS
    print("🔟 Guardando artefactos...")
    
    os.makedirs("models", exist_ok=True)
    
    # CAMBIO: Incluir horizonte en el nombre del modelo
    model_path = f"models/modelo_xgb_{version}_h{horizonte}.joblib"
    joblib.dump(xgb_model, model_path)
    print(f"   ✅ Modelo: {model_path}")
    
    # Metadata con horizonte
    metadata = {
        "version": version,
        "horizonte_dias": horizonte,
        "tipo_modelo": "XGBoost",
        "fecha_entrenamiento": datetime.now().isoformat(),
        "n_train": len(X_train),
        "n_test": len(X_test),
        "n_features": len(feature_cols),
        "feature_cols": feature_cols,
        "hiperparametros": {
            "n_estimators": 200,
            "max_depth": 5,
            "learning_rate": 0.1,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "scale_pos_weight": float(scale_pos_weight),
            "random_state": 42
        },
        "threshold_default": 0.5,
        "threshold_optimo": float(threshold_optimo),
        "metricas_threshold_default": {
            "auc": float(auc_default),
            "precision": float(precision_default),
            "recall": float(recall_default),
            "f1_score": float(f1_default)
        },
        "metricas_threshold_optimo": {
            "auc": float(auc_optimo),
            "precision": float(precision_optimo),
            "recall": float(recall_optimo),
            "f1_score": float(f1_optimo)
        }
    }
    
    metadata_path = f"models/metadata_xgb_{version}_h{horizonte}.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2, default=str)
    print(f"   ✅ Metadata: {metadata_path}\n")
    
    return True

def main():
    """Entrena modelos para TODOS los horizontes"""
    print("\n" + "="*70)
    print("🎯 ENTRENAMIENTO MULTIHORIZONTE - XGBOOST")
    print("="*70)
    print(f"\nHorizontes a entrenar: {HORIZONTES_ENTRENAMIENTO}\n")

    # 0. CARGAR PANEL COMPLETO
    print("Cargando panel de entrenamiento...")
    try:
        panel = pd.read_parquet("data/processed/panel_entrenamiento.parquet")
        print(f"✅ {panel.shape[0]} filas × {panel.shape[1]} columnas")
        print(f"Horizontes en el panel: {sorted(panel['horizonte_dias'].unique())}\n")
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

    # Entrenar para cada horizonte
    resultados = {}
    for horizonte in HORIZONTES_ENTRENAMIENTO:
        exitoso = entrenar_horizonte(panel, horizonte, version="v1.0")
        resultados[horizonte] = exitoso

    # Resumen final
    print("\n" + "="*70)
    print("✅ ENTRENAMIENTO MULTIHORIZONTE COMPLETADO")
    print("="*70)
    print("\nResumen por horizonte:")
    for horizonte, exitoso in resultados.items():
        estado = "✅ OK" if exitoso else "❌ ERROR"
        print(f"  Horizonte {horizonte:2d} días: {estado}")
    
    print("\nModelos guardados:")
    for horizonte in HORIZONTES_ENTRENAMIENTO:
        print(f"  • models/modelo_xgb_v1.0_h{horizonte}.joblib")
    
    print("\n" + "="*70 + "\n")
    
    return all(resultados.values())

if __name__ == "__main__":
    exitoso = main()
    sys.exit(0 if exitoso else 1)
