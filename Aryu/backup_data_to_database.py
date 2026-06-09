import os
import subprocess

# ---------- CONFIG ----------
DB_NAME = "aylms_live"
DB_USER = "aylms_live"
DB_PASSWORD = "KfdW543FDdfg"
DB_HOST = "69.62.78.109"
DB_PORT = "5432"

BACKUP_DIR = "/home/aryu_user/Arun/Live Backup/01-06-26"

# Only Lead-related backups
SQL_FILES = [
    "01-06-26_public_aryuapp_lead.sql",
    "01-06-26_public_aryuapp_leadcalllog.sql",
    "01-06-26_public_aryuapp_leaddmlog.sql",
    "01-06-26_public_aryuapp_leadfollowup.sql",
    "01-06-26_public_aryuapp_leadstatushistory.sql",
]
# -----------------------------

env = os.environ.copy()
env["PGPASSWORD"] = DB_PASSWORD

for file_name in SQL_FILES:
    file_path = os.path.join(BACKUP_DIR, file_name)

    if not os.path.exists(file_path):
        print(f"⚠️ File not found: {file_path}")
        continue

    print(f"🚀 Restoring: {file_name}")

    try:
        subprocess.run(
            [
                "psql",
                "-h", DB_HOST,
                "-p", DB_PORT,
                "-U", DB_USER,
                "-d", DB_NAME,
                "-f", file_path,
            ],
            env=env,
            check=True,
        )

        print(f"✅ {file_name} restored successfully.\n")

    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to restore {file_name}")
        print(e)