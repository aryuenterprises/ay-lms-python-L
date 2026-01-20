import os
import subprocess
import datetime
import psycopg2

# === CONFIG ===
DB_NAME = "academy_management_staging"
DB_USER = "academy_user"
DB_HOST = "69.62.78.109"
DB_PASSWORD = "c2lC47v"
BACKUP_ROOT = r"C:\\Users\\aryue\\OneDrive\\Desktop\\academystaging-python\\db-staging-backup"

# === CREATE DATE FOLDER ===
today = datetime.date.today().strftime("%d-%m-%y")
backup_dir = os.path.join(BACKUP_ROOT, today)
os.makedirs(backup_dir, exist_ok=True)

# === CONNECT TO DB ===
conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, host=DB_HOST, password=DB_PASSWORD)
cur = conn.cursor()
cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='livequiz';")
tables = [t[0] for t in cur.fetchall()]
conn.close()

# === LOOP AND BACKUP EACH TABLE ===
for table in tables:
    filename = f"{today}_{table}.sql"
    filepath = os.path.join(backup_dir, filename)
    cmd = [
        "pg_dump",
        "-U", DB_USER,
        "-h", DB_HOST,
        "-d", DB_NAME,
        "-t", table,
        "-f", filepath
    ]
    # Run pg_dump with environment password
    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASSWORD
    subprocess.run(cmd, env=env, check=True)
    print(f" Backed up: {filename}")

print(f"\n All tables backed up successfully in folder: {backup_dir}")
