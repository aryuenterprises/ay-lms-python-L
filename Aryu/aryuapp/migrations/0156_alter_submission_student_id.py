from django.db import migrations, models
import django.db.models.deletion
from aryuapp.models import Student

def migrate_student_ids(apps, schema_editor):
    Submission = apps.get_model('aryuapp', 'Submission')
    Student = apps.get_model('aryuapp', 'Student')

    for sub in Submission.objects.all():
        try:
            student = Student.objects.get(registration_id=sub.student_id)  # old varchar
            sub.student_tmp = student
            sub.save(update_fields=['student_tmp'])
        except Student.DoesNotExist:
            continue 

class Migration(migrations.Migration):

    dependencies = [
        ('aryuapp', '0155_alter_attendance_student_id_migrate'),
    ]

    operations = [
        # Step 1: Add temporary FK field
        migrations.AddField(
            model_name='submission',
            name='student_tmp',
            field=models.ForeignKey(
                to='aryuapp.Student',
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='+'
            ),
        ),

        # Step 2: Populate temporary field
        migrations.RunPython(migrate_student_ids, reverse_code=migrations.RunPython.noop),

        # Step 3: Remove old varchar field
        migrations.RemoveField(
            model_name='submission',
            name='student',
        ),

        # Step 4: Rename temporary FK to original name
        migrations.RenameField(
            model_name='submission',
            old_name='student_tmp',
            new_name='student',
        ),
    ]