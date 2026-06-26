import os
from datetime import datetime
import subprocess
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("❌ DATABASE_URL no configurada")
    exit(1)

fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
archivo_backup = f"backup_paneles_dashboard_{fecha}.sql"

print(f"📦 Respaldando tabla paneles... → {archivo_backup}")

# Extraer credenciales
from urllib.parse import urlparse
parsed = urlparse(DATABASE_URL)
user = parsed.username
password = parsed.password
host = parsed.hostname
port = parsed.port or 5432
database = parsed.path.lstrip('/')

# Usar pg_dump
cmd = f'PGPASSWORD="{password}" pg_dump -h {host} -p {port} -U {user} -d {database} -t paneles > {archivo_backup}'
result = subprocess.run(cmd, shell=True)

if result.returncode == 0:
    print(f"✅ Backup completado: {archivo_backup}")
else:
    print(f"❌ Error en backup")
