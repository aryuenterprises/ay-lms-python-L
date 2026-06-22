import os
import subprocess
import datetime
import psycopg2

DB_NAME = "aylms_live"
DB_USER = "aylms_live"
DB_HOST = "69.62.78.109"
DB_PASSWORD = "KfdW543FDdfg"
BACKUP_ROOT = "/home/aryu_user/Arun/Live Backup/"

PG_DUMP = "/usr/lib/postgresql/16/bin/pg_dump"

today = datetime.date.today().strftime("%d-%m-%y")
backup_dir = os.path.join(BACKUP_ROOT, today)
os.makedirs(backup_dir, exist_ok=True)

# --- fetch schema + table ---
conn = psycopg2.connect(
    dbname=DB_NAME,
    user=DB_USER,
    host=DB_HOST,
    password=DB_PASSWORD
)
cur = conn.cursor()

cur.execute("""
    SELECT schemaname, tablename
    FROM pg_tables
    WHERE schemaname IN ('public', 'livequiz')
""")

tables = cur.fetchall()
conn.close()

# --- backup ---
for schema, table in tables:
    filename = f"{today}_{schema}_{table}.sql"
    filepath = os.path.join(backup_dir, filename)

    cmd = [
        PG_DUMP,
        "-U", DB_USER,
        "-h", DB_HOST,
        "-d", DB_NAME,
        "-t", f"{schema}.{table}",
        "-f", filepath
    ]

    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASSWORD

    subprocess.run(cmd, env=env, check=True)
    print(f"Backed up: {schema}.{table}")

print(f"\nAll tables backed up successfully in: {backup_dir}")