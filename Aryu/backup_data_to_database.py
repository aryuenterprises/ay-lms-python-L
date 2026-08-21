import os
import re
import subprocess

# Database Credentials
DB_HOST = "187.127.178.144"
DB_PORT = "5432"
DB_USER = "aylms_live"
DB_NAME = "aylms_live"
DB_PASSWORD = "KfdW543FDdfg"

# Backup Directory Path
BACKUP_DIR = "/home/tamilselvi/Documents/backup/14-08-26"

# Specific dump files to process (leave empty [] to process all .sql files in directory)
TARGET_FILES = [
    "14-08-26_public_aryuapp_classschedule.sql"
    # "14-08-26_public_resume_usersubscription.sql",
]

env = os.environ.copy()
env["PGPASSWORD"] = DB_PASSWORD


def run_psql_command(sql_script):
    """Executes SQL commands inside psql process."""
    process = subprocess.Popen(
        [
            "psql",
            "-h", DB_HOST,
            "-p", DB_PORT,
            "-U", DB_USER,
            "-d", DB_NAME,
            "-v", "ON_ERROR_STOP=1"
        ],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    stdout, stderr = process.communicate(input=sql_script)
    return process.returncode, stdout, stderr


def restore_dump_file(file_path):
    file_name = os.path.basename(file_path)
    print(f"\n==================================================")
    print(f"📦 Processing Dump File: {file_name}")

    with open(file_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    # 1. Determine target table name
    table_match = re.search(r"COPY\s+([a-zA-Z0-9_\"\.]+)\s*\(", sql_content, re.IGNORECASE)
    if not table_match:
        table_match = re.search(r"INSERT\s+INTO\s+([a-zA-Z0-9_\"\.]+)\s*", sql_content, re.IGNORECASE)

    if not table_match:
        print(f"⚠️ Skipped: Could not detect target table name in {file_name}")
        return

    full_table_name = table_match.group(1)
    
    # Split schema and table name
    if "." in full_table_name:
        schema_name, table_name = full_table_name.split(".", 1)
        schema_name = schema_name.replace('"', '')
        table_name = table_name.replace('"', '')
    else:
        schema_name = "public"
        table_name = full_table_name.replace('"', '')

    print(f"🎯 Target Table: {schema_name}.{table_name}")

    # 2. Extract Data Section (COPY / INSERT)
    copy_match = re.search(r"(COPY\s+" + re.escape(full_table_name) + r".*?\\\.)", sql_content, re.DOTALL)
    if copy_match:
        data_sql = copy_match.group(1)
    else:
        insert_lines = [
            line for line in sql_content.splitlines()
            if line.strip().startswith(f"INSERT INTO {full_table_name}")
        ]
        data_sql = "\n".join(insert_lines)

    if not data_sql.strip():
        print(f"⚠️ Skipped: No data records (COPY/INSERT) found in {file_name}")
        return

    # 3. Dynamic Foreign Key Removal Block (Drops ALL FKs pointing to or from this table)
    drop_and_restore_fks_script = f"""
    DO $$
    DECLARE
        r RECORD;
    BEGIN
        -- Step A: Drop all constraints referencing or belonging to this table
        FOR r IN 
            SELECT tc.table_schema, tc.table_name, tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.referential_constraints rc 
                ON tc.constraint_name = rc.constraint_name
            JOIN information_schema.constraint_column_usage ccu 
                ON rc.unique_constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND ((tc.table_schema = '{schema_name}' AND tc.table_name = '{table_name}')
                OR (ccu.constraint_schema = '{schema_name}' AND ccu.table_name = '{table_name}'))
        LOOP
            EXECUTE format('ALTER TABLE %I.%I DROP CONSTRAINT IF EXISTS %I;', r.table_schema, r.table_name, r.constraint_name);
        END LOOP;
    END $$;
    """

    rc1, stdout1, stderr1 = run_psql_command(f"BEGIN;\n{drop_and_restore_fks_script}\nCOMMIT;")
    if rc1 != 0:
        print(f"❌ Failed to drop Foreign Keys for '{schema_name}.{table_name}':\n{stderr1}")
        return

    # 4. Clear table, Restore Data, and Sync Sequence
    data_restore_script = f"""
    BEGIN;

    DELETE FROM {schema_name}.{table_name};

    {data_sql}

    DO $$
    DECLARE
        seq_name text;
        pk_col text;
        max_val bigint;
    BEGIN
        SELECT a.attname INTO pk_col
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = '{schema_name}.{table_name}'::regclass AND i.indisprimary
        LIMIT 1;

        IF pk_col IS NOT NULL THEN
            seq_name := pg_get_serial_sequence('{schema_name}.{table_name}', pk_col);
            IF seq_name IS NOT NULL THEN
                EXECUTE format('SELECT COALESCE(MAX(%I), 1) FROM {schema_name}.{table_name}', pk_col) INTO max_val;
                PERFORM setval(seq_name, max_val);
            END IF;
        END IF;
    END $$;

    COMMIT;
    """

    rc2, stdout2, stderr2 = run_psql_command(data_restore_script)
    if rc2 != 0:
        print(f"❌ Data Restore Failed for '{schema_name}.{table_name}':\n{stderr2}")
        return

    # 5. Extract and Re-attach Foreign Keys from current file as NOT VALID
    fk_constraints = re.findall(
        r"ALTER TABLE ONLY\s+([a-zA-Z0-9_\"\.]+)\s+ADD CONSTRAINT\s+([a-zA-Z0-9_]+)\s+FOREIGN KEY\s*\((.*?)\)\s*REFERENCES\s*([a-zA-Z0-9_\"\.]+)\((.*?)\)",
        sql_content,
        re.IGNORECASE
    )

    readd_fk_statements = []
    for full_tbl, fk_name, col, ref_tbl, ref_col in fk_constraints:
        readd_fk_statements.append(
            f"ALTER TABLE {full_tbl} ADD CONSTRAINT {fk_name} FOREIGN KEY ({col}) "
            f"REFERENCES {ref_tbl}({ref_col}) DEFERRABLE INITIALLY DEFERRED NOT VALID;"
        )

    readd_fk_sql = "\n".join(readd_fk_statements) if readd_fk_statements else "-- No FKs to re-add"

    rc3, stdout3, stderr3 = run_psql_command(f"BEGIN;\n{readd_fk_sql}\nCOMMIT;")
    if rc3 == 0:
        print(f"✅ RESTORE SUCCESSFUL: Restored data into '{schema_name}.{table_name}'")
    else:
        print(f"⚠️ Data restored, but FK re-attach warning for '{schema_name}.{table_name}':\n{stderr3}")


def main():
    if not os.path.exists(BACKUP_DIR):
        print(f"❌ Backup directory not found: {BACKUP_DIR}")
        return

    if TARGET_FILES:
        files = [os.path.join(BACKUP_DIR, f) for f in TARGET_FILES]
    else:
        files = [
            os.path.join(BACKUP_DIR, f)
            for f in os.listdir(BACKUP_DIR)
            if f.endswith(".sql")
        ]

    print(f"🚀 Found {len(files)} files to inspect and restore...")

    for dump_file in sorted(files):
        if os.path.exists(dump_file):
            restore_dump_file(dump_file)
        else:
            print(f"❌ Backup file missing: {dump_file}")


if __name__ == "__main__":
    main()