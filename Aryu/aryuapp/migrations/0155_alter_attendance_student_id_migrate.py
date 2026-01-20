from django.db import migrations

def migrate_m2m_student_ids(apps, schema_editor):
    # Step 1: Add temporary integer column to the M2M table
    schema_editor.execute("""
        ALTER TABLE aryuapp_student_course_name
        ADD COLUMN student_id_tmp integer;
    """)

    # Step 2: Populate temporary column using mapping from registration_id
    schema_editor.execute("""
        UPDATE aryuapp_student_course_name scn
        SET student_id_tmp = s.student_id
        FROM aryuapp_student s
        WHERE scn.registration_id = s.registration_id;
    """)

    # Step 3: Drop old varchar student_id
    schema_editor.execute("""
        ALTER TABLE aryuapp_student_course_name
        DROP COLUMN registration_id;
    """)

    # Step 4: Rename temporary column to student_id
    schema_editor.execute("""
        ALTER TABLE aryuapp_student_course_name
        RENAME COLUMN student_id_tmp TO student_id;
    """)

    # Step 5: Add foreign key constraint
    schema_editor.execute("""
        ALTER TABLE aryuapp_student_course_name
        ADD CONSTRAINT student_id_fk
        FOREIGN KEY (student_id) REFERENCES aryuapp_student(student_id)
        ON DELETE CASCADE;
    """)

class Migration(migrations.Migration):

    dependencies = [
        ('aryuapp', '0154_alter_attendance_student_id'),  # adjust as needed
    ]

    operations = [
        migrations.RunPython(migrate_m2m_student_ids),
    ]
