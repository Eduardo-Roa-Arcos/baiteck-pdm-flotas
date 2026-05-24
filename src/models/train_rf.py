# src/models/train_rf.py
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import pandas as pd
import numpy as np
import joblib
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    precision_score, recall_score, f1_score, 
    roc_auc_score, classification_report, confusion_matrix
)

def temporal_split(df: pd.DataFrame, test_size: float = 0.3):
    """Split simple: 70% train, 30% test"""
    split_idx = int(len(df) * (1 - test_size))
    train = df.iloc[:split_idx].copy()
    test = df.iloc[split_idx:].copy()
    return train, test

def entrenar_random_forest(version: str = "v1.0"):
    """Pipeline completo"""
    print("\n" + "="*70)
    print("🌲 ENTRENAMIENTO RANDOM FOREST")
    print("="*70 + "\n")

    # 1. CARGAR
    print("1️⃣  Cargando panel...")
    try:
        panel = pd.read_parquet("data/processed/panel_entrenamiento.parquet")
        print(f"   ✅ {panel.shape[0]} filas × {panel.shape[1]} columnas\n")
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

    # 2. FEATURES (ANTES del split)
    print("2️⃣  Identificando features...")
    drop_cols = ["target", "activo_id", "fecha_corte", "horizonte_dias", 
                 "patente", "marca", "modelo", "tipo_vehiculo", "fecha_alta_flota"]
    feature_cols = [c for c in panel.columns if c not in drop_cols]
    print(f"   ✅ {len(feature_cols)} features: {feature_cols}\n")

    # 3. SPLIT
    print("3️⃣  Split temporal...")
    train, test = temporal_split(panel, test_size=0.3)
    print(f"   ✅ Train: {len(train)} | Test: {len(test)}\n")

    # 4. PREPARAR X, y
    print("4️⃣  Preparando features...")
    X_train = train[feature_cols].fillna(-1)
    y_train = train["target"]
    X_test = test[feature_cols].fillna(-1)
    y_test = test["target"]
    print(f"   ✅ X_train: {X_train.shape} | X_test: {X_test.shape}\n")

    # 5. ENTRENAR
    print("5️⃣  Entrenando...")
    rf = RandomForestClassifier(
        n_estimators=100, max_depth=12, min_samples_leaf=5,
        class_weight="balanced", n_jobs=-1, random_state=42
    )
    rf.fit(X_train, y_train)
    print("   ✅ Modelo entrenado\n")

    # 6. EVALUAR
    print("6️⃣  Evaluando...")
    y_pred = rf.predict(X_test)
    y_pred_proba_full = rf.predict_proba(X_test)
    
    # Manejar caso donde solo hay una clase
    if y_pred_proba_full.shape[1] == 1:
        print(f"   ⚠️  Solo una clase en test: {np.unique(y_test)}")
        y_pred_proba = np.where(y_pred == 1, 0.9, 0.1)
    else:
        y_pred_proba = y_pred_proba_full[:, 1]

    auc = roc_auc_score(y_test, y_pred_proba) if len(np.unique(y_test)) > 1 else 0.0
    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)

    print(f"   AUC: {auc:.4f} | Precision: {precision:.4f}")
    print(f"   Recall: {recall:.4f} | F1: {f1:.4f}\n")
    print(classification_report(y_test, y_pred))

    # 7. GUARDAR
    print("7️⃣  Guardando...")
    joblib.dump(rf, f"models/modelo_rf_{version}.joblib")
    print(f"   ✅ Guardado: modelo_rf_{version}.joblib\n")

    print("="*70)
    print(f"✨ Random Forest {version} - COMPLETADO")
    print("="*70 + "\n")
    return True

def main():
    entrenar_random_forest(version="v1.0")

if __name__ == "__main__":
    main()
