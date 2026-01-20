from django.db import migrations, models

def migrate_student_ids(apps, schema_editor):
    # Tables with 'registration_id' column
    tables_with_registration = [
        "aryuapp_recordings",
        "aryuapp_invoice",
        "aryuapp_notification",
        "aryuapp_chatroom",
    ]

    for table in tables_with_registration:
        schema_editor.execute(f"""
            -- 1. Add temporary column
            ALTER TABLE {table} ADD COLUMN student_id_tmp integer;

            -- 2. Copy over student_id using registration_id match
            UPDATE {table} t
            SET student_id_tmp = s.student_id
            FROM aryuapp_student s
            WHERE t.registration_id = s.registration_id;

            -- 3. Drop the old registration_id column
            ALTER TABLE {table} DROP COLUMN registration_id;

            -- 4. Rename the new column
            ALTER TABLE {table} RENAME COLUMN student_id_tmp TO student_id;
        """)

    # Special case: leave_request already has student_id but as varchar
    schema_editor.execute("""
        ALTER TABLE leave_request ADD COLUMN student_id_tmp integer;

        UPDATE leave_request lr
        SET student_id_tmp = s.student_id
        FROM aryuapp_student s
        WHERE lr.student_id = s.registration_id;

        ALTER TABLE leave_request DROP COLUMN student_id;

        ALTER TABLE leave_request RENAME COLUMN student_id_tmp TO student_id;
    """)

class Migration(migrations.Migration):

    dependencies = [
        ('aryuapp', '0160_alter_student_types'),
    ]

    operations = [
        migrations.RunPython(migrate_student_ids),
    ]