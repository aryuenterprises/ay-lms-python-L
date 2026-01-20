from django.db import migrations, models
from django.db import migrations


def convert_student_id_to_int(apps, schema_editor):
    """
    Safely convert the varchar student_id to integer.
    """
    # Raw SQL execution
    schema_editor.execute("""
        -- Step 1: Rename old column
        ALTER TABLE aryuapp_studenttopicstatus RENAME COLUMN student_id TO student_id_old;

        -- Step 2: Add new integer column (nullable for now)
        ALTER TABLE aryuapp_studenttopicstatus ADD COLUMN student_id integer;

        -- Step 3: Update new column with integer cast
        UPDATE aryuapp_studenttopicstatus
        SET student_id = student_id_old::integer
        WHERE student_id_old ~ '^\d+$';  -- only numeric values

        -- Step 4: If there are any rows not matching numeric pattern, you can set a default or delete them
        -- Example: delete invalid rows
        DELETE FROM aryuapp_studenttopicstatus
        WHERE student_id IS NULL;

        -- Step 5: Set NOT NULL constraint on new column
        ALTER TABLE aryuapp_studenttopicstatus
        ALTER COLUMN student_id SET NOT NULL;

        -- Step 6: Drop old column
        ALTER TABLE aryuapp_studenttopicstatus DROP COLUMN student_id_old;
    """)

class Migration(migrations.Migration):

    dependencies = [
        ('aryuapp', '0157_alter_test_result_student_id'),  # Replace with your latest migration
    ]

    operations = [
        migrations.RunPython(convert_student_id_to_int),

        # Finally, ensure Django sees the field as proper ForeignKey
        migrations.AlterField(
            model_name='studenttopicstatus',
            name='student',
            field=models.ForeignKey(
                to='aryuapp.Student',
                on_delete=models.CASCADE,
                related_name='topic_statuses',
            ),
        ),
    ]