import joblib
import os

print("Directorio actual:", os.getcwd())
print("Archivos en models/:")
os.system("ls -la models/")

print("\nCargando modelo directamente...")
modelo = joblib.load("models/modelo_xgb_v1.joblib")
print("✅ Modelo cargado")
print(f"  - model: {modelo['model']}")
print(f"  - pipeline: {modelo['pipeline']}")
print(f"  - feature_cols: {modelo['feature_cols']}")

print("\nAhora probando Predictor...")
from predictor import Predictor
p = Predictor()
print(f"self.model: {p.model}")
print(f"self.pipeline: {p.pipeline}")
print(f"self.feature_cols: {p.feature_cols}")
