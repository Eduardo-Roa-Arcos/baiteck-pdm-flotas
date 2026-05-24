from pathlib import Path
import os
from dotenv import load_dotenv
import pandas as pd
import numpy as np
from sqlalchemy import text
from src.db import engine
from datetime import datetime  
import json
import joblib

# Cargar variables de entorno
load_dotenv('.env')

RAW_DIR = Path("data/raw")

def load_csv_files():
    """Carga CSVs a Supabase"""
    try:
        with engine.connect() as conn:
            conn.execute(text("TRUNCATE TABLE activos CASCADE"))
            conn.execute(text("TRUNCATE TABLE ordenes_trabajo CASCADE"))
            conn.execute(text("TRUNCATE TABLE repuestos_consumidos CASCADE"))
            conn.commit()

        # Cargar activos
        activos_path = RAW_DIR / "activos.csv"
        if activos_path.exists():
            df = pd.read_csv(activos_path)
            df.to_sql("activos", engine, if_exists="append", index=False, method="multi", chunksize=1000)
            print(f"✅ Cargados {len(df)} activos")

        # Cargar órdenes de trabajo
        ot_path = RAW_DIR / "ordenes_trabajo.csv"
        if ot_path.exists():
            df = pd.read_csv(ot_path)
            df.to_sql("ordenes_trabajo", engine, if_exists="append", index=False, method="multi", chunksize=1000)
            print(f"✅ Cargadas {len(df)} órdenes de trabajo")

        # Cargar repuestos
        rp_path = RAW_DIR / "repuestos_consumidos.csv"
        if rp_path.exists():
            df = pd.read_csv(rp_path)
            df.to_sql("repuestos_consumidos", engine, if_exists="append", index=False, method="multi", chunksize=1000)
            print(f"✅ Cargados {len(df)} repuestos")

    except Exception as e:
        print(f"⚠️ Error cargando CSVs: {e}")

def construir_features(fecha_corte_str: str, horizonte_dias: int = 30) -> pd.DataFrame:
    """Construye dataset de features para modelado"""

    # Cargar datos
    activos = pd.read_sql("SELECT * FROM activos", engine)
    ots = pd.read_sql("SELECT * FROM ordenes_trabajo", engine)

    # Convertir fechas a string para comparación simple
    ots["fecha_apertura_str"] = pd.to_datetime(ots["fecha_apertura"]).astype(str).str[:10]
    activos["fecha_alta_flota_str"] = pd.to_datetime(activos["fecha_alta_flota"]).astype(str).str[:10]

    # OTs antes de la fecha de corte
    ots_pasado = ots[ots["fecha_apertura_str"] < fecha_corte_str].copy()

    # Base de features
    features = activos[["activo_id", "patente", "marca", "modelo", "tipo_vehiculo"]].copy()
    features["fecha_corte"] = fecha_corte_str
    features["horizonte_dias"] = horizonte_dias

    # Edad del activo (en días aproximados)
    dias_transcurridos = (pd.Timestamp(fecha_corte_str) - pd.to_datetime(activos["fecha_alta_flota"])).dt.days
    features["edad_dias"] = dias_transcurridos.fillna(-1).astype(int)

    # Conteo de OTs en últimos 30, 90, 180 días
    for dias in [30, 90, 180]:
        fecha_inicio_str = (pd.Timestamp(fecha_corte_str) - pd.Timedelta(days=dias)).strftime("%Y-%m-%d")
        ots_ventana = ots_pasado[ots_pasado["fecha_apertura_str"] >= fecha_inicio_str]

        # Total de OTs
        total_ots = ots_ventana.groupby("activo_id").size().rename(f"ot_{dias}d")
        features = features.merge(total_ots, on="activo_id", how="left")

        # OTs correctivas
        ots_corr = ots_ventana[ots_ventana["tipo_ot"].str.lower() == "correctiva"]
        count_corr = ots_corr.groupby("activo_id").size().rename(f"corr_{dias}d")
        features = features.merge(count_corr, on="activo_id", how="left")

    # TARGET: ¿habrá correctiva en próximos N días?
    fecha_fin_str = (pd.Timestamp(fecha_corte_str) + pd.Timedelta(days=horizonte_dias)).strftime("%Y-%m-%d")
    ots_futuras = ots[(ots["fecha_apertura_str"] >= fecha_corte_str) & 
                      (ots["fecha_apertura_str"] < fecha_fin_str)]
    ots_correctivas = ots_futuras[ots_futuras["tipo_ot"].str.lower() == "correctiva"]

    activos_falla = set(ots_correctivas["activo_id"].unique())
    features["target"] = features["activo_id"].isin(activos_falla).astype(int)

    # Rellenar NaNs
    numeric_cols = features.select_dtypes(include=[np.number]).columns
    features[numeric_cols] = features[numeric_cols].fillna(-1)

    return features

def generar_panel_entrenamiento(fecha_inicio: str, fecha_fin: str, paso_dias: int = 7) -> pd.DataFrame:
    """
    Genera panel temporal con múltiples snapshots.
    Cada fila = activo en una fecha de corte diferente
    Respeta la regla: solo información ANTES de cada fecha de corte
    """
    import os

    # Crear directorio si no existe
    os.makedirs("data/processed", exist_ok=True)

    # Generar fechas de corte cada N días
    fechas = pd.date_range(fecha_inicio, fecha_fin, freq=f"{paso_dias}D")
    paneles = []

    print(f"\n📅 Generando panel de entrenamiento...")
    print(f"   Período: {fecha_inicio} a {fecha_fin}")
    print(f"   Paso: {paso_dias} días")
    print(f"   Total de snapshots: {len(fechas)}\n")

    for i, fecha in enumerate(fechas):
        fecha_str = str(fecha.date())
        print(f"   [{i+1}/{len(fechas)}] Procesando {fecha_str}...", end=" ")

        try:
            df = construir_features(fecha_str, horizonte_dias=30)
            if len(df) > 0:
                paneles.append(df)
                print(f"✅ ({len(df)} activos)")
            else:
                print("⚠️ (0 activos)")
        except Exception as e:
            print(f"❌ Error: {str(e)[:50]}")

    if len(paneles) == 0:
        print("\n❌ No se generaron snapshots")
        return pd.DataFrame()

    # Concatenar todos los snapshots
    panel = pd.concat(paneles, ignore_index=True)

    # Guardar como parquet
    salida = "data/processed/panel_entrenamiento.parquet"
    panel.to_parquet(salida, index=False)
    print(f"\n✅ Panel generado:")
    print(f"   Shape: {panel.shape[0]} filas × {panel.shape[1]} columnas")
    print(f"   Archivo: {salida}")
    print(f"   Target distribution:\n{panel['target'].value_counts()}\n")

    return panel

def main():
    print("Hello from baiteck-pdm-flotas!")
    load_csv_files()

    # Generar panel de entrenamiento
    # Usa rango de fechas dentro de tus datos (mayo 2024)
    panel = generar_panel_entrenamiento(
        fecha_inicio="2024-05-01",
        fecha_fin="2024-05-15",
        paso_dias=3  # Snapshot cada 3 días para tener suficientes datos
    )

    if len(panel) > 0:
        print("📊 Muestra del panel:")
        print(panel[["activo_id", "patente", "fecha_corte", "edad_dias", "ot_30d", "target"]].head(10))

    print("\n📊 Generando features...")
    df_features = construir_features("2024-05-10", horizonte_dias=5)
    print(f"\n✅ Dataset de features generado: {df_features.shape[0]} filas × {df_features.shape[1]} columnas")
    print(f"\nTarget distribution:\n{df_features['target'].value_counts()}")
    print(f"\nMuestra:\n{df_features.head()}")

def entrenar_random_forest():
    """Entrena Random Forest y lo registra en Supabase"""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score, classification_report
    import joblib
    import json

    print("\n" + "="*70)
    print("🌲 ENTRENAMIENTO RANDOM FOREST")
    print("="*70 + "\n")

    # 1. Cargar panel
    print("1️⃣  Cargando panel...")
    panel = pd.read_parquet("data/processed/panel_entrenamiento.parquet")
    print(f"   ✅ {panel.shape[0]} × {panel.shape[1]}\n")

    # 2. Split temporal
    print("2️⃣  Split temporal (80/20)...")
    test_date = "2024-05-10"
    train = panel[panel["fecha_corte"].astype(str) < test_date]
    test = panel[panel["fecha_corte"].astype(str) >= test_date]
    print(f"   ✅ Train: {len(train)} | Test: {len(test)}\n")

    # 3. Preparar features
    print("3️⃣  Preparando features...")
    drop_cols = ["target", "activo_id", "fecha_corte", "horizonte_dias", 
                 "patente", "marca", "modelo", "tipo_vehiculo", "fecha_alta_flota"]
    feature_cols = [c for c in panel.columns if c not in drop_cols]

    X_train = train[feature_cols].fillna(-1)
    y_train = train["target"]
    X_test = test[feature_cols].fillna(-1)
    y_test = test["target"]

    # Reemplazar -1 con mediana
    for col in X_train.select_dtypes(include=[np.number]).columns:
        if (X_train[col] == -1).any():
            median = X_train[X_train[col] != -1][col].median()
            X_train.loc[X_train[col] == -1, col] = median if not pd.isna(median) else 0
            X_test.loc[X_test[col] == -1, col] = median if not pd.isna(median) else 0

    print(f"   ✅ Features: {len(feature_cols)}\n")

    # 4. Entrenar RF
    print("4️⃣  Entrenando Random Forest...")
    rf_params = {
        "n_estimators": 100,
        "max_depth": 12,
        "min_samples_leaf": 5,
        "min_samples_split": 10,
        "class_weight": "balanced",
        "random_state": 42
    }

    rf = RandomForestClassifier(**rf_params)
    rf.fit(X_train, y_train)
    print("   ✅ Entrenado\n")

    # 5. Evaluar
    print("5️⃣  Evaluando...")
    y_pred = rf.predict(X_test)

    # Manejar caso donde test set tiene solo una clase
    try:
        y_pred_proba = rf.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, y_pred_proba)
    except (IndexError, ValueError):
        # Si hay solo una clase, usar y_pred directamente
        y_pred_proba = y_pred.astype(float)
        auc = 0.0  # No se puede calcular AUC con una sola clase
        print("   ⚠️  Test set tiene solo una clase (AUC = 0)")

    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)

    print(f"   AUC: {auc:.4f} | Precision: {precision:.4f} | Recall: {recall:.4f} | F1: {f1:.4f}\n")
    # 6. Guardar
    print("6️⃣  Guardando modelo...")
    nombre = "modelo_rf_v1.joblib"
    joblib.dump(rf, f"models/{nombre}")
    print(f"   ✅ Guardado: models/{nombre}\n")

    # 7. Registrar en Supabase
    print("7️⃣  Registrando en Supabase...")
    query = """
    INSERT INTO modelos_registro (
        version, nombre_archivo, fecha_entrenamiento,
        auc_score, precision, recall, f1_score,
        n_samples_train, n_features, features_utilizadas,
        hiperparametros, entrenado_por, notas
    ) VALUES (
        :version, :nombre_archivo, :fecha_entrenamiento,
        :auc_score, :precision, :recall, :f1_score,
        :n_samples, :n_features, :features,
        :hiperparametros, :entrenado_por, :notas
    )
    RETURNING modelo_id;
    """

    with engine.connect() as conn:
        result = conn.execute(text(query), {
            "version": "v1_rf",
            "nombre_archivo": nombre,
            "fecha_entrenamiento": datetime.now().date(),
            "auc_score": float(auc),
            "precision": float(precision),
            "recall": float(recall),
            "f1_score": float(f1),
            "n_samples": len(X_train),
            "n_features": len(feature_cols),
            "features": feature_cols,
            "hiperparametros": json.dumps(rf_params),
            "entrenado_por": "sistema_rf",
            "notas": "Random Forest baseline"
        })
        conn.commit()
        modelo_id = result.fetchone()[0]

    print(f"   ✅ Registrado: {modelo_id}\n")

    print("="*70)
    print("✨ Random Forest entrenado exitosamente")
    print("="*70 + "\n")

def entrenar_xgboost():
    """Entrena XGBoost con early stopping y validación temporal"""
    import xgboost as xgb
    from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score

    print("\n" + "="*70)
    print("🚀 ENTRENAMIENTO XGBOOST")
    print("="*70 + "\n")

    # 1. Cargar panel
    print("1️⃣  Cargando panel...")
    panel = pd.read_parquet("data/processed/panel_entrenamiento.parquet")
    print(f"   ✅ {panel.shape[0]} × {panel.shape[1]}\n")

    # 2. Split temporal (70% train, 15% val, 15% test)
    print("2️⃣  Split temporal...")
    panel["fecha_corte_str"] = panel["fecha_corte"].astype(str)

    n = len(panel)
    train_idx = int(n * 0.70)
    val_idx = int(n * 0.85)

    train = panel[:train_idx]
    val = panel[train_idx:val_idx]
    test = panel[val_idx:]

    print(f"   ✅ Train: {len(train)} | Val: {len(val)} | Test: {len(test)}\n")

    # 3. Preparar features
    print("3️⃣  Preparando features...")
    drop_cols = ["target", "activo_id", "fecha_corte", "horizonte_dias",
                 "patente", "marca", "modelo", "tipo_vehiculo", "fecha_alta_flota", "fecha_corte_str"]
    feature_cols = [c for c in panel.columns if c not in drop_cols]

    X_train = train[feature_cols].fillna(-1).copy()
    y_train = train["target"].copy()
    X_val = val[feature_cols].fillna(-1).copy()
    y_val = val["target"].copy()
    X_test = test[feature_cols].fillna(-1).copy()
    y_test = test["target"].copy()

    # Reemplazar -1 con mediana
    for col in X_train.select_dtypes(include=[np.number]).columns:
        if (X_train[col] == -1).any():
            median = X_train[X_train[col] != -1][col].median()
            X_train.loc[X_train[col] == -1, col] = median if not pd.isna(median) else 0
            X_val.loc[X_val[col] == -1, col] = median if not pd.isna(median) else 0
            X_test.loc[X_test[col] == -1, col] = median if not pd.isna(median) else 0

    print(f"   ✅ Features: {len(feature_cols)}\n")

    # 4. Calcular class weight para desbalance
    print("4️⃣  Calculando pesos para desbalance...")
    neg_count = (y_train == 0).sum()
    pos_count = (y_train == 1).sum()
    scale_pos_weight = neg_count / max(pos_count, 1)
    print(f"   ✅ Negatives: {neg_count} | Positives: {pos_count}")
    print(f"   ✅ scale_pos_weight: {scale_pos_weight:.2f}\n")

    # 5. Entrenar XGBoost con early stopping
    print("5️⃣  Entrenando XGBoost...")

    xgb_params = {
        "n_estimators": 500,
        "max_depth": 6,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "scale_pos_weight": scale_pos_weight,
        "random_state": 42,
        "eval_metric": "auc",
        "early_stopping_rounds": 50
    }

    xgb_model = xgb.XGBClassifier(**xgb_params)

    # Fit con validation set para early stopping
    xgb_model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=10
    )

    print("   ✅ Entrenado\n")

    # 6. Evaluar en test
    print("6️⃣  Evaluando...")
    y_pred = xgb_model.predict(X_test)
    y_pred_proba = xgb_model.predict_proba(X_test)[:, 1]

    try:
        auc = roc_auc_score(y_test, y_pred_proba)
    except:
        auc = 0.0

    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)

    print(f"   AUC: {auc:.4f} | Precision: {precision:.4f} | Recall: {recall:.4f} | F1: {f1:.4f}\n")

    # 7. Feature importance
    print("7️⃣  Feature importance:")
    importances = pd.DataFrame({
        "feature": feature_cols,
        "importance": xgb_model.feature_importances_
    }).sort_values("importance", ascending=False).head(10)
    print(importances.to_string(index=False))
    print()

    # 8. Guardar modelo
    print("8️⃣  Guardando modelo...")
    artifact = {
    "model": xgb_model,
    "pipeline": None,
    "feature_cols": feature_cols
    }
    nombre = "modelo_xgb_v1.joblib"
    joblib.dump(artifact, f"models/{nombre}")
    print(f"   ✅ Guardado: models/{nombre}\n")

    # 9. Registrar en Supabase
    print("9️⃣  Registrando en Supabase...")
    query = """
    INSERT INTO modelos_registro (
        version, nombre_archivo, fecha_entrenamiento,
        auc_score, precision, recall, f1_score,
        n_samples_train, n_features, features_utilizadas,
        hiperparametros, entrenado_por, notas
    ) VALUES (
        :version, :nombre_archivo, :fecha_entrenamiento,
        :auc_score, :precision, :recall, :f1_score,
        :n_samples, :n_features, :features,
        :hiperparametros, :entrenado_por, :notas
    )
    RETURNING modelo_id;
    """

    with engine.connect() as conn:
        result = conn.execute(text(query), {
            "version": "v1_xgb",
            "nombre_archivo": nombre,
            "fecha_entrenamiento": datetime.now().date(),
            "auc_score": float(auc),
            "precision": float(precision),
            "recall": float(recall),
            "f1_score": float(f1),
            "n_samples": len(X_train),
            "n_features": len(feature_cols),
            "features": feature_cols,
            "hiperparametros": json.dumps(xgb_params),
            "entrenado_por": "sistema_xgb",
            "notas": "XGBoost con early stopping y validación temporal"
        })
        conn.commit()
        modelo_id = result.fetchone()[0]

    print(f"   ✅ Registrado: {modelo_id}\n")

    print("="*70)
    print("✨ XGBoost entrenado exitosamente")
    print("="*70 + "\n")

    return xgb_model

if __name__ == "__main__":
    main()

# ============================================================
# 9. SCORING DIARIO
# ============================================================

# La función ejecutar_scoring_diario ya está en scoring_diario.py
# Solo importarla si quieres usarla desde main

def ejecutar_scoring_diario_desde_main(fecha_scoring: str = None, horizonte_dias: int = 30):
    """Wrapper para ejecutar scoring desde main"""
    from scoring_diario import ejecutar_scoring_diario
    return ejecutar_scoring_diario(fecha_scoring, horizonte_dias)
