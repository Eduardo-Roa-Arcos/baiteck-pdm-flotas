#!/usr/bin/env python3
"""Ver probabilidades predichas por el modelo para cada horizonte"""

import sys
import json
import pandas as pd
import joblib
import numpy as np
from datetime import date
from src.features.build_features import construir_features

MODEL_PATH = "models/modelo_xgb_v1.0.joblib"
METADATA_PATH = "models/metadata_xgb_v1.0.json"

MAPEO_COLUMNAS = {
    'ot_30d': 'count_ot_30d',
    'ot_90d': 'count_ot_90d',
    'ot_180d': 'count_ot_180d',
    'corr_30d': 'count_correctivas_30d',
    'corr_90d': 'count_correctivas_90d',
    'corr_180d': 'count_correctivas_180d',
}

def main():
    fecha = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    
    # Cargar modelo
    model = joblib.load(MODEL_PATH)
    with open(METADATA_PATH, "r") as f:
        metadata = json.load(f)
    
    feature_cols = metadata["feature_cols"]
    mapeo_largo_a_corto = {v: k for k, v in MAPEO_COLUMNAS.items()}
    
    print("="*70)
    print("🎯 DIAGNÓSTICO: Probabilidades predichas por horizonte")
    print("="*70)
    
    for horizonte in [7, 30, 90]:
        print(f"\n{'='*70}")
        print(f"HORIZONTE {horizonte} DÍAS")
        print(f"{'='*70}")
        
        # Construir features
        features = construir_features(fecha, horizonte_dias=horizonte)
        
        # Mapear columnas
        feature_cols_largos = [MAPEO_COLUMNAS.get(col, col) for col in feature_cols]
        X = features[feature_cols_largos].copy()
        X = X.rename(columns=mapeo_largo_a_corto)
        X = X.fillna(-1)
        
        # Predicción
        proba = model.predict_proba(X)[:, 1]
        
        print(f"\nProbabilidades de falla:")
        print(f"  Min:    {proba.min():.4f}")
        print(f"  Media:  {proba.mean():.4f}")
        print(f"  Mediana: {np.median(proba):.4f}")
        print(f"  Max:    {proba.max():.4f}")
        print(f"  Std:    {proba.std():.4f}")
        
        # Contar por rango
        print(f"\nDistribución:")
        for threshold in [0.3, 0.6, 0.8]:
            count = (proba >= threshold).sum()
            pct = count / len(proba) * 100
            print(f"  Proba >= {threshold}: {count:4d} ({pct:5.1f}%)")

if __name__ == "__main__":
    main()
