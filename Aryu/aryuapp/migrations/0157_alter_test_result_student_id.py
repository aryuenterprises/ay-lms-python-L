from django.db import migrations, models
import django.db.models.deletion

def migrate_testresult_student_ids(apps, schema_editor):
    TestResult = apps.get_model('aryuapp', 'TestResult')
    Student = apps.get_model('aryuapp', 'Student')

    for tr in TestResult.objects.all():
        try:
            # old student_id_id stores registration_id as varchar
            student = Student.objects.get(registration_id=tr.student_id_id)
            tr.student_tmp = student
            tr.save(update_fields=['student_tmp'])
        except Student.DoesNotExist:
            continue 
        
class Migration(migrations.Migration):

    dependencies = [
        ('aryuapp', '0156_alter_submission_student_id'),
    ]

    operations = [
        # Step 1: Add temporary FK field
        migrations.AddField(
            model_name='testresult',
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
        migrations.RunPython(migrate_testresult_student_ids, reverse_code=migrations.RunPython.noop),

        # Step 3: Remove old varchar field
        migrations.RemoveField(
            model_name='testresult',
            name='student_id',
        ),

        # Step 4: Rename temporary FK to original name
        migrations.RenameField(
            model_name='testresult',
            old_name='student_tmp',
            new_name='student_id',
        ),
    ]