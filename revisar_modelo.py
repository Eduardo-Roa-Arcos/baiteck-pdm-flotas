import joblib

modelo = joblib.load("models/modelo_xgb_v1.joblib")
print("Tipo:", type(modelo))
print("Contenido:")
if isinstance(modelo, dict):
    for key in modelo.keys():
        print(f"  - {key}: {type(modelo[key])}")
else:
    print("  No es dict, es:", dir(modelo))
