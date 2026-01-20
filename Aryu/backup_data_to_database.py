import os
import subprocess

# ---------- CONFIG ----------
DB_NAME = "academy_management_staging"
DB_USER = "academy_user"
DB_PASSWORD = "c2lC47v"
DB_HOST = "69.62.78.109"
DB_PORT = "5432"

BACKUP_DIR = r"D:\\LMS - Summa\\academystaging-python\\Aryu\\db_backups\\06-11-25"
# -----------------------------

# Copy environment and inject password
env = os.environ.copy()
env["PGPASSWORD"] = DB_PASSWORD

# Collect all .sql files in directory
sql_files = [os.path.join(BACKUP_DIR, f) for f in os.listdir(BACKUP_DIR) if f.lower().endswith(".sql")]
sql_files.sort()

if not sql_files:
    print("⚠️ No SQL files found in the backup directory.")
else:
    for file_path in sql_files:
        print(f"🚀 Restoring: {file_path} ...")
        try:
            subprocess.run(
                [
                    "psql",
                    "-h", DB_HOST,
                    "-p", DB_PORT,
                    "-U", DB_USER,
                    "-d", DB_NAME,
                    "-f", file_path
                ],
                env=env,        # pass env with password
                check=True,
                shell=True,     # needed on Windows
            )
            print(f"✅ {os.path.basename(file_path)} restored successfully.\n")
        except subprocess.CalledProcessError as e:
            print(f"❌ Error restoring {os.path.basename(file_path)}: {e}\n")
