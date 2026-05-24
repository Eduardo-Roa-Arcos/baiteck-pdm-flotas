cd /users/eduardoroa/baiteck-pdm-flotas      
uv run python ejecutar_workflow.py
uv run python -m src.models.train_rf   
uv run python -m src.models.train_xgboost
uv run python ejecutar_scoring.py 

