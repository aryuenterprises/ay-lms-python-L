from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aryuapp', '0162_alter_trainers_assigned_student'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                UPDATE aryuapp_studentanswers sa
                SET student_id_id = s.student_id
                FROM aryuapp_student s
                WHERE sa.student_id_id = s.registration_id;
            """,
            reverse_sql="""
                -- Optional: Add reverse if you need rollback
                -- This assumes you had stored the original registration_id somewhere
                -- Otherwise, leave this as an empty SQL string
            """
        )
    ]