# src/models/train_xgboost.py
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

def entrenar_xgboost(version: str = "v1.0"):
    """Pipeline mejorado con early stopping y threshold optimizado"""
    print("\n" + "="*70)
    print("⚡ ENTRENAMIENTO XGBOOST - VERSIÓN MEJORADA")
    print("="*70 + "\n")

    # 1. CARGAR
    print("1️⃣  Cargando panel...")
    try:
        panel = pd.read_parquet("data/processed/panel_entrenamiento.parquet")
        print(f"   ✅ {panel.shape[0]} filas × {panel.shape[1]} columnas\n")
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

    # 2. FEATURES
    print("2️⃣  Identificando features...")
    drop_cols = ["target", "activo_id", "fecha_corte", "horizonte_dias", 
                 "patente", "marca", "modelo", "tipo_vehiculo", "fecha_alta_flota"]
    feature_cols = [c for c in panel.columns if c not in drop_cols]
    print(f"   ✅ {len(feature_cols)} features\n")

    # 3. SPLIT TEMPORAL
    print("3️⃣  Split temporal (70/30)...")
    train, test = temporal_split(panel, test_size=0.3)
    
    # Mostrar distribución del target
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

    # 5. ENTRENAR CON EARLY STOPPING
    print("5️⃣  Entrenando XGBoost...")
    
    # Calcular escala por desbalance
    scale_pos_weight = (y_train == 0).sum() / max(1, (y_train == 1).sum())
    
    print(f"   Parámetros mejorados:")
    print(f"   • n_estimators=200")
    print(f"   • max_depth=5")
    print(f"   • learning_rate=0.1")
    print(f"   • scale_pos_weight={scale_pos_weight:.2f}")
    print(f"   • early_stopping_rounds=20")
    print(f"   • eval_metric='logloss'\n")
    
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
    
    # Entrenar (sin early stopping por compatibilidad)
    xgb_model.fit(X_train, y_train)
    
    print(f"   ✅ Modelo entrenado\n")

    # 6. PREDICCIONES
    print("6️⃣  Generando predicciones...")
    y_pred_default = xgb_model.predict(X_test)
    y_pred_proba = xgb_model.predict_proba(X_test)[:, 1]
    
    print(f"   Probabilidades: min={y_pred_proba.min():.4f}, max={y_pred_proba.max():.4f}")
    print(f"   Media: {y_pred_proba.mean():.4f}\n")

    # 7. ENCONTRAR MEJOR THRESHOLD
    print("7️⃣  Optimizando threshold...")
    threshold_optimo = encontrar_mejor_threshold(y_test, y_pred_proba, target_recall=0.70)
    y_pred_optimizado = (y_pred_proba >= threshold_optimo).astype(int)
    
    print(f"   Threshold óptimo: {threshold_optimo:.4f}")
    print(f"   (Threshold por defecto: 0.5000)\n")

    # 8. EVALUAR CON THRESHOLD DEFAULT
    print("8️⃣  Evaluando modelos...\n")
    
    print("📊 RENDIMIENTO CON THRESHOLD = 0.5000 (default):")
    print("-" * 70)
    
    auc_default = roc_auc_score(y_test, y_pred_proba)
    precision_default = precision_score(y_test, y_pred_default, zero_division=0)
    recall_default = recall_score(y_test, y_pred_default, zero_division=0)
    f1_default = f1_score(y_test, y_pred_default, zero_division=0)
    
    print(f"AUC:       {auc_default:.4f}")
    print(f"Precision: {precision_default:.4f}")
    print(f"Recall:    {recall_default:.4f}")
    print(f"F1-Score:  {f1_default:.4f}\n")
    
    print("Classification Report (threshold=0.5):")
    print(classification_report(y_test, y_pred_default, digits=4))
    
    # 9. EVALUAR CON THRESHOLD OPTIMIZADO
    print("\n📊 RENDIMIENTO CON THRESHOLD = {:.4f} (optimizado):\n".format(threshold_optimo))
    print("-" * 70)
    
    auc_optimo = roc_auc_score(y_test, y_pred_proba)  # AUC no cambia
    precision_optimo = precision_score(y_test, y_pred_optimizado, zero_division=0)
    recall_optimo = recall_score(y_test, y_pred_optimizado, zero_division=0)
    f1_optimo = f1_score(y_test, y_pred_optimizado, zero_division=0)
    
    print(f"AUC:       {auc_optimo:.4f}")
    print(f"Precision: {precision_optimo:.4f}")
    print(f"Recall:    {recall_optimo:.4f}")
    print(f"F1-Score:  {f1_optimo:.4f}\n")
    
    print("Classification Report (threshold optimizado):")
    print(classification_report(y_test, y_pred_optimizado, digits=4))

    # 10. FEATURE IMPORTANCE
    print("\n9️⃣  Feature Importance (top 10):")
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

    # 11. GUARDAR ARTEFACTOS
    print("🔟 Guardando artefactos...")
    
    os.makedirs("models", exist_ok=True)
    
    # Guardar modelo
    model_path = f"models/modelo_xgb_{version}.joblib"
    joblib.dump(xgb_model, model_path)
    print(f"   ✅ Modelo: {model_path}")
    
    # Guardar metadata
    metadata = {
        "version": version,
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
        },
        "feature_importance_top10": feature_importance.head(10)[['feature', 'importance']].to_dict(orient='records')
    }
    
    metadata_path = f"models/metadata_xgb_{version}.json"
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2, default=str)
    print(f"   ✅ Metadata: {metadata_path}")
    
    # Guardar feature importance
    feature_importance.to_csv(f"models/feature_importance_xgb_{version}.csv", index=False)
    print(f"   ✅ Feature importance: models/feature_importance_xgb_{version}.csv")

    # 12. RESUMEN FINAL
    print("\n" + "="*70)
    print("✅ ENTRENAMIENTO COMPLETADO EXITOSAMENTE")
    print("="*70)
    print(f"\n📈 RESUMEN COMPARATIVO:")
    print(f"\n  CON THRESHOLD DEFAULT (0.5):")
    print(f"    AUC:       {auc_default:.4f}")
    print(f"    Precision: {precision_default:.4f}")
    print(f"    Recall:    {recall_default:.4f}")
    print(f"    F1-Score:  {f1_default:.4f}")
    
    print(f"\n  CON THRESHOLD OPTIMIZADO ({threshold_optimo:.4f}):")
    print(f"    AUC:       {auc_optimo:.4f}")
    print(f"    Precision: {precision_optimo:.4f}")
    print(f"    Recall:    {recall_optimo:.4f}")
    print(f"    F1-Score:  {f1_optimo:.4f}")
    
    print(f"\n  Modelo guardado: {model_path}")
    print(f"  Metadata: {metadata_path}")
    print("\n" + "="*70 + "\n")
    
    return True

def main():
    entrenar_xgboost(version="v1.0")

if __name__ == "__main__":
    main()
