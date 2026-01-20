
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('aryuapp', '0153_alter_batchcoursetrainer_student'),
    ]

    operations = [
        migrations.AddField(
            model_name='attendance',
            name='student_id_tmp',
            field=models.IntegerField(null=True),
        ),
        migrations.RunSQL(
            sql="""
                UPDATE attendance a
                SET student_id_tmp = s.student_id
                FROM aryuapp_student s
                WHERE a.student_id = s.registration_id;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RemoveField(
            model_name='attendance',
            name='student',
        ),
        migrations.RenameField(
            model_name='attendance',
            old_name='student_id_tmp',
            new_name='student_id',
        ),
        migrations.AlterField(
            model_name='attendance',
            name='student_id',
            field=models.ForeignKey(
                to='aryuapp.Student',
                on_delete=django.db.models.deletion.CASCADE,
                to_field='student_id',
                db_column='student_id',
            ),
        ),
    ]
