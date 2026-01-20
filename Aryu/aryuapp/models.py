from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
from django.utils import timezone
from django.contrib.postgres.fields import ArrayField
from datetime import timedelta, datetime, time
import string
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from rest_framework.exceptions import ValidationError
from datetime import date
import pytz
from django.db.models import F, ExpressionWrapper, DateTimeField, Q
from django.core.validators import MaxValueValidator



def validate_image_or_svg(file):
    if not file.name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg')):
        raise ValidationError('Unsupported file type.')

class Settings(models.Model):
    company_name = models.CharField(max_length=100, null=True, blank=True)
    company_address = models.CharField(max_length=100, null=True, blank=True)
    company_contact = models.CharField(max_length=100, null=True, blank=True)
    company_email = models.CharField(max_length=100, null=True, blank=True)
    company_website = models.CharField(max_length=100, null=True, blank=True)
    bank_name = models.CharField(max_length=100, null=True, blank=True)
    bank_branch = models.CharField(max_length=100, null=True, blank=True)
    bank_account_no = models.CharField(max_length=100, null=True, blank=True)
    bank_ifsc = models.CharField(max_length=100, null=True, blank=True)
    general_logo = models.FileField(upload_to='logos/', null=True, blank=True, validators=[validate_image_or_svg])
    secondary_logo = models.FileField(upload_to='logos/', null=True, blank=True, validators=[validate_image_or_svg])
    signature = models.FileField(upload_to='signatures/', null=True, blank=True, validators=[validate_image_or_svg])
    gst_detail = models.CharField(max_length=100, null=True, blank=True)
    declaration = models.TextField(max_length=100, null=True, blank=True)
    attendance_options = models.CharField(max_length=100, null=True, blank=True)
    deactivation_options = models.CharField(max_length=100, null=True, blank=True)
    payment_method = models.CharField(max_length=100, null=True, blank=True)
    stripe_enabled = models.BooleanField(default=True)
    paypal_enabled = models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "settings"

class ReleaseNote(models.Model):
    version = models.CharField(max_length=20)  # e.g. "V1.0", "V1.1"
    title = models.CharField(max_length=200, null=True, blank=True)
    content = models.TextField()  # full release notes text/HTML/Markdown
    release_notes = models.FileField(upload_to='release_notes/', null = True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.version

class CMS(models.Model):
    title = models.CharField(max_length=100, null=True, blank=True)
    link = models.CharField(max_length=100, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Note(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    note_text = models.TextField(null=True, blank=True)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    reason = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=20, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Note on {self.content_object} - {self.note_text[:30]}"

def get_ist_now():
    ist = pytz.timezone('Asia/Kolkata')
    now = timezone.now().astimezone(ist)
    return now.replace(microsecond=0)

class UserManager(BaseUserManager):
    def create_user(self, username, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(username, email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    id = models.AutoField(primary_key=True)
    full_name = models.CharField(max_length=100)
    username = models.CharField(max_length=100, unique=True)
    email = models.EmailField(unique=True)
    user_type = models.CharField(max_length=20, null=True, blank=True)
    ph_no = models.CharField(max_length=20, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    role = models.ForeignKey("Role", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    
    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]

    objects = UserManager()

    class Meta:
        db_table = "users"

class ModulePermission(models.Model):
    module_id = models.AutoField(primary_key=True)
    module = models.CharField(max_length=50, unique=True)
    actions = ArrayField(
        base_field=models.CharField(max_length=20),
        default=list,
        help_text='List of actions allowed for this module'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        db_table = "module_permissions"

    def __str__(self):
        return f"{self.module} - {self.actions}"

class Role(models.Model):
    role_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        db_table = "roles"

    def __str__(self):
        return self.name

class RoleModulePermission(models.Model):
    id = models.AutoField(primary_key=True)
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="module_permissions")
    module_permission = models.ForeignKey(ModulePermission, on_delete=models.CASCADE)
    allowed_actions = ArrayField(
        base_field=models.CharField(max_length=20),
        default=list,
        help_text='Actions allowed for this role in this module'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        unique_together = ("role", "module_permission")
        db_table = "role_module_permissions"

    def __str__(self):
        return f"{self.role} - {self.module_permission.module} - {self.allowed_actions}"

class CourseCategory(models.Model):
    category_id = models.AutoField(primary_key=True)
    category_name = models.CharField(max_length=100)
    category_pic = models.ImageField(upload_to='course_categories/', null=True, blank=True)
    status = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def cascade_category_deactivation(self):
        # Deactivate all courses under this category
        courses = Course.objects.filter(course_category=self, status="Active")
        IST = pytz.timezone("Asia/Kolkata")
        now = timezone.now().astimezone(IST)

        for course in courses:
            # Deactivate the course
            course.status = "Inactive"
            course.save(update_fields=["status"])

            # ---- Handle NewBatch only ----
            new_batches = NewBatch.objects.filter(course=course, is_archived=False)

            # Deactivate batches
            new_batches.update(status=False)

            # ---- Archive upcoming schedules (only new_batch) ----
            schedules_qs = ClassSchedule.objects.filter(
                course=course,
                new_batch__in=new_batches,
                is_archived=False
            ).select_related("new_batch")

            schedules_to_archive = []

            for sched in schedules_qs:
                sched_date = sched.scheduled_date
                start_time = sched.start_time or time(0, 0)
                end_time = sched.end_time or time(23, 59, 59)

                start_dt = IST.localize(datetime.combine(sched_date, start_time))
                end_dt = IST.localize(datetime.combine(sched_date, end_time))

                # Archive only future schedules
                if end_dt > now:
                    schedules_to_archive.append(sched.schedule_id)

            if schedules_to_archive:
                ClassSchedule.objects.filter(
                    schedule_id__in=schedules_to_archive
                ).update(is_archived=True)

    def __str__(self):
        return self.category_name

class Course(models.Model):
    course_id = models.AutoField(primary_key=True)
    course_category = models.ForeignKey(
        CourseCategory,
        on_delete=models.CASCADE,
        related_name="courses"
    )
    course_name = models.CharField(max_length=255, null=True, blank=True)
    course_pic = models.ImageField(upload_to="courses/", null=True, blank=True)
    syllabus = models.FileField(upload_to="syllabus/", null=True, blank=True)
    duration = models.CharField(max_length=3, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    internship_duration = models.CharField(max_length=3, null=True, blank=True)
    mode_of_delivery = models.CharField(max_length=100, null=True, blank=True)
    currency_type = models.CharField(max_length=100, null=True, blank=True)
    fee_type = models.CharField(max_length=100, null=True, blank=True)
    fee = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MaxValueValidator(100000)], null=True, blank=True
    )
    status = models.CharField(max_length=20, null=True, blank=True)
    notes = models.CharField(max_length=255, null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def deactivate_course(self, course):
        IST = pytz.timezone("Asia/Kolkata")
        now = timezone.now().astimezone(IST)

        # Step 1: Deactivate the course
        course.status = "Inactive"
        course.save(update_fields=["status"])

        # Step 2: Deactivate related new batches
        new_batches = NewBatch.objects.filter(course=course, is_archived=False)
        new_batches.update(status=False)

        # Step 3: Archive only upcoming schedules linked to NewBatch
        schedules_qs = ClassSchedule.objects.filter(
            course=course,
            new_batch__in=new_batches,
            is_archived=False
        ).select_related("new_batch")

        schedules_to_archive = []

        for sched in schedules_qs:
            sched_date = sched.scheduled_date
            start_time = sched.start_time or time(0, 0)
            end_time = sched.end_time or time(23, 59, 59)

            start_dt = IST.localize(datetime.combine(sched_date, start_time))
            end_dt = IST.localize(datetime.combine(sched_date, end_time))

            # Archive only future schedules
            if end_dt > now:
                schedules_to_archive.append(sched.schedule_id)

        if schedules_to_archive:
            ClassSchedule.objects.filter(
                schedule_id__in=schedules_to_archive
            ).update(is_archived=True)

    def __str__(self):
        return self.course_name

def trainer_profile_pic_path(instance, filename):
        reg_id = str(instance.employee_id).replace(" ", "_")
        return f'trainer_profile_pics/{reg_id}/{filename}'
    
def trainer_expense_bill_path(instance, filename):
    trainer_id = str(instance.expense.trainer.employee_id).replace(" ", "_")
    expense_id = str(instance.expense.expense_id)
    return f"trainer_expenses/{trainer_id}/{expense_id}/{filename}"

class Trainer(models.Model):
    trainer_id = models.AutoField(primary_key=True, db_index=True)
    employee_id = models.CharField(max_length=255, unique=True, db_index=True)
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True)
    username = models.CharField(max_length=50)
    password = models.CharField(max_length=128, null=False, blank=False)
    full_name = models.CharField(max_length=255, db_index=True)
    user_type = models.CharField(max_length=20, null=False, blank=False, db_index=True)
    profile_pic = models.ImageField(upload_to=trainer_profile_pic_path, null=True, blank=True)
    email = models.EmailField()
    contact_no = models.CharField(max_length=20)
    gender = models.CharField(max_length=10, null=True, blank=True)
    specialization = models.CharField(max_length=255, null=True, blank=True)
    working_hours = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(max_length=20, null=True, blank=True, db_index=True)
    notes = GenericRelation("Note", related_query_name="trainer_notes")
    is_archived = models.BooleanField(default=False, db_index=True)
    created_by = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['trainer_id']),
            models.Index(fields=['employee_id']),
            models.Index(fields=['full_name', 'user_type']),
            models.Index(fields=['created_by', 'created_by_type']),
            models.Index(fields=['status', 'is_archived']),
        ]

class TrainerTravelExpense(models.Model):
    expense_id = models.AutoField(primary_key=True, db_index=True)
    trainer = models.ForeignKey('Trainer', on_delete=models.CASCADE, related_name="travel_expenses")
    travel_date = models.DateField()
    description = models.TextField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=50, default="pending", db_index=True)
    remarks = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(default=False, db_index=True)

    def __str__(self):
        return f"{self.trainer.full_name} - {self.travel_date}"

class TrainerTravelExpenseImage(models.Model):
    image_id = models.AutoField(primary_key=True)
    expense = models.ForeignKey(TrainerTravelExpense, on_delete=models.CASCADE, related_name="bills")
    image = models.FileField(upload_to=trainer_expense_bill_path)
    uploaded_at = models.DateTimeField(auto_now_add=True)

class TrainerAttendance(models.Model):
    trainer = models.ForeignKey(
        'Trainer',
        on_delete=models.CASCADE,
        to_field='employee_id',
        db_column='employee_id',
        null=False
    )
    new_batch = models.ForeignKey(
        "NewBatch",
        on_delete=models.CASCADE,
        null=True,
        related_name='trainer_attendance'
    )
    schedule_id = models.ForeignKey(
        'CLassSchedule',
        on_delete=models.CASCADE,
        null=True, blank=True
    )
    batch = models.ForeignKey("Batch", null=True, blank=True, on_delete=models.SET_NULL)
    date = models.DateTimeField(null=False, blank=False)
    status = models.CharField(max_length=10)
    course =models.ForeignKey(Course, on_delete=models.CASCADE, null=False, blank=False)
    topic = models.TextField(blank=True)
    sub_topic = models.TextField(blank=True)
    marked_by_admin = models.BooleanField(default=False)

    class Meta:
        db_table = 'trainer_attendance'

class Topic(models.Model):
    topic_id = models.AutoField(primary_key=True)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='topics')
    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    create_by = models.ForeignKey(Trainer, on_delete=models.SET_NULL, null=True, related_name='created_topics', blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    

def student_profile_pic_path(instance, filename):
        reg_id = str(instance.registration_id).replace(" ", "_")
        return f'profile_pics/{reg_id}/{filename}'

class Student(models.Model):
    student_id = models.AutoField(primary_key=True)
    registration_id = models.CharField(max_length=50, unique=True)
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True)
    profile_pic = models.ImageField(upload_to=student_profile_pic_path, null=True, blank=True)
    username = models.CharField(max_length=50, null=False, blank=False)
    password = models.CharField(max_length=128, null=False, blank=False)
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    is_archived = models.BooleanField(default=False)
    dob = models.DateField()
    email = models.EmailField( null=False, blank=False)
    contact_no = models.CharField(max_length=20, null=False, blank=False)
    current_address = models.TextField(max_length=255, null=False, blank=False)
    permanent_address = models.TextField(max_length=255, null=False, blank=False)
    joining_date = models.DateField(auto_now_add=True)
    internship = models.CharField(max_length=3, null=True, blank=True)
    city = models.CharField(max_length=255, null=False, blank=False)
    state = models.CharField(max_length=255, null=False, blank=False)
    country = models.CharField(max_length=255, null=False, blank=False) 
    parent_guardian_name = models.CharField(max_length=255, null=True, blank=True)
    parent_guardian_phone = models.CharField(max_length=20, null=True, blank=True)
    parent_guardian_occupation = models.CharField(max_length=255, null=True, blank=True)
    trainer = models.ForeignKey(Trainer, on_delete=models.SET_NULL, null=True, blank=True, related_name='students')
    reference_number = models.CharField(max_length=255, null=True, blank=True)
    student_type = models.CharField(max_length=30, null=False, blank=False)
    status = models.BooleanField(default=True, null=False, blank=False)
    notes = GenericRelation("Note", related_query_name="student_notes")
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower()  # force lowercase before saving
        if not self.registration_id:
            self.registration_id = self.generate_registration_id()
        super().save(*args, **kwargs)

    def generate_registration_id(self):
        prefix = "AYA"
        current_date = get_ist_now()
        month = current_date.strftime("%m")
        year = current_date.strftime("%y")

        from .models import Student  # avoid circular import
        students = Student.objects.filter(registration_id__contains=f"{month}{year}")
        count = students.count() + 1 
        number = (count - 1) % 999 + 1
        return f"{prefix}{month}{year}{number:03d}"
    def __str__(self):
        return f"{self.first_name} {self.last_name}"

class Employer(models.Model):
    """ Represents a company """
    company_id = models.AutoField(primary_key=True)
    email = models.EmailField(null=True, blank=True)
    company_name = models.CharField(max_length=255, null=True, blank=True)
    contact_person = models.CharField(max_length=255, null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    address = models.CharField(max_length=255, null=True, blank=True)
    status = models.BooleanField(default=True, null=True, blank=True)
    notes = models.CharField(max_length=255, null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'client_company_details'

    def save(self, *args, **kwargs):
        if self.pk:
            old_status = Employer.objects.get(pk=self.pk).status
            if old_status != self.status and self.status is False:
                # Deactivate all linked sub-admins
                self.sub_admins.update(status=False)

                # Deactivate all linked students
                # School students
                school_students = Student.objects.filter(
                    student_id__in=self.group_school.values_list('student__student_id', flat=True)
                )
                school_students.update(status=False)

                # College students
                college_students = Student.objects.filter(
                    student_id__in=self.group_college.values_list('student__student_id', flat=True)
                )
                college_students.update(status=False)

                # Employees
                employee_students = Student.objects.filter(
                    student_id__in=self.group_employees.values_list('student__student_id', flat=True)
                )
                employee_students.update(status=False)
                
            elif old_status != self.status and self.status is True:
                # Deactivate all linked sub-admins
                self.sub_admins.update(status=True)

                # Deactivate all linked students
                # School students
                school_students = Student.objects.filter(
                    student_id__in=self.group_school.values_list('student__student_id', flat=True)
                )
                school_students.update(status=True)

                # College students
                college_students = Student.objects.filter(
                    student_id__in=self.group_college.values_list('student__student_id', flat=True)
                )
                college_students.update(status=True)

                # Employees
                employee_students = Student.objects.filter(
                    student_id__in=self.group_employees.values_list('student__student_id', flat=True)
                )
                employee_students.update(status=True)   

        super().save(*args, **kwargs)

class SubAdmin(models.Model):
    """Manager or HR for a company."""
    company = models.ForeignKey(Employer, on_delete=models.CASCADE, related_name='sub_admins')
    employer_id = models.AutoField(primary_key=True)
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True)
    full_name = models.CharField(max_length=255)
    email = models.EmailField(null=True, blank=True)
    phone_no = models.CharField(max_length=14, null=True, blank=True)
    username = models.CharField(max_length=50)
    password = models.CharField(max_length=128)
    designation = models.CharField(max_length=50, default="sub_admin", null=True, blank=True)
    status = models.BooleanField(default=True, null=True, blank=True)
    notes = models.CharField(max_length=255, null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sub_admins'

class School_Student(models.Model):
    student = models.OneToOneField(
        Student,
        on_delete=models.CASCADE,
        to_field='student_id',
        db_column='student_id',
        related_name='school_student'
    )
    company_id = models.ForeignKey(
        Employer,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="group_school"
    )
    school_name = models.CharField(max_length=255)
    school_class = models.CharField(max_length=255)

class College_Student(models.Model):
    student = models.OneToOneField(
        Student,
        on_delete=models.CASCADE,
        to_field='student_id',
        db_column='student_id',
        related_name='college_student'
    )
    company_id = models.ForeignKey(
        Employer,
        on_delete=models.SET_NULL,
        null=True, blank=True, 
        related_name="group_college"
    )
    college_name = models.CharField(max_length=255, null=False, blank=False)
    degree = models.CharField(max_length=255, null=False, blank=False)
    resume = models.FileField(upload_to='resumes/', null=True, blank=True)
    year_of_study = models.IntegerField(null=False, blank=False)

class JobSeeker(models.Model):
    student = models.OneToOneField(
        Student,
        on_delete=models.CASCADE,
        to_field='student_id',
        db_column='student_id',
        related_name='jobseeker'  
    )
    company_id = models.ForeignKey(
        Employer,
        on_delete=models.SET_NULL,
        null=True, blank=True, 
        related_name="group_jobseeker"
    )
    passed_out_year = models.IntegerField(null=False, blank=False)
    current_qualification = models.CharField(max_length=255, null=False, blank=False)
    preferred_job_role = models.CharField(max_length=255, null=False, blank=False)
    resume = models.FileField(upload_to= 'resume/', null=True, blank=True)
     
class Employee(models.Model):
    student = models.OneToOneField(
        Student,
        on_delete=models.CASCADE,
        to_field='student_id',
        db_column='student_id',
        related_name='employee'  
    )
    company_id = models.ForeignKey(
        Employer,
        on_delete=models.SET_NULL,
        null=True, blank=True, 
        related_name="group_employees"
    )
    company_name = models.CharField(max_length=255, null=False, blank=False)
    designation = models.CharField(max_length=255, null=False, blank=False)
    experience = models.CharField(max_length=255, default="0", null=False, blank=False)
    skills = models.TextField(null=False, blank=True)

class StudentTopicStatus(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="topic_statuses")
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="student_statuses")
    status = models.BooleanField(default=True)
    ratings = models.IntegerField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    
class Recordings(models.Model):
    id = models.AutoField(primary_key=True)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="recordings")
    topic = models.CharField(max_length=255, null=True, blank=True)
    recording = models.TextField(null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
class Attendance(models.Model):
    
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        to_field='student_id',
        db_column='student_id', null=False
    )
    schedule_id = models.ForeignKey(
        'CLassSchedule',
        on_delete=models.CASCADE,
        null=True, blank=True
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        null=False,
        related_name='attendances'
    )
    new_batch = models.ForeignKey(
        "NewBatch",
        on_delete=models.CASCADE,
        null=True,
        related_name='attendance'
    )
    batch = models.ForeignKey("Batch", null=True, blank=True, on_delete=models.SET_NULL)
    date = models.DateTimeField(null=False, blank=False)
    status = models.CharField(max_length=10)
    ip_address= models.GenericIPAddressField(null=True, blank=True)
    marked_by_admin = models.BooleanField(default=False)

    class Meta:
        db_table = 'attendance'
    
class Invoice(models.Model):
    invoice_number = models.CharField(max_length=50, unique=True, editable=False)
    date = models.DateField(default=timezone.now)
    payment_terms = models.CharField(max_length=100, blank=True, null=True)
    
    student = models.ForeignKey(
        Student,  # replace 'Student' with the actual Student model if different
        on_delete=models.CASCADE,
        related_name='invoices'
    )
    # Buyer details
    buyer_name = models.CharField(max_length=255)
    buyer_address = models.TextField()
    buyer_mobile = models.CharField(max_length=20, blank=True, null=True)

    # Service details
    description = models.TextField()
    quantity = models.PositiveIntegerField()
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    per = models.CharField(max_length=50, default="Nos")
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    # Amount in words
    amount_in_words = models.CharField(max_length=255)

    # PDF file
    pdf_file = models.FileField(upload_to='invoice/', blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            today = timezone.now()
            prefix = "AYA"  # Fixed prefix
            month = today.strftime("%m")  # 07
            year = today.strftime("%y")   # 25

            # Find the last invoice for this month/year
            last_invoice = Invoice.objects.filter(
                invoice_number__startswith=f"{prefix}{month}{year}"
            ).order_by('-invoice_number').first()

            if last_invoice:
                last_seq = int(last_invoice.invoice_number[-3:])
                new_seq = last_seq + 1
            else:
                new_seq = 1

            self.invoice_number = f"{prefix}{month}{year}{new_seq:03d}"

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.buyer_name}"
    
class Certificate(models.Model):
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        to_field='student_id',
        db_column='student_id', null=False
    )
    certificate_number = models.CharField(max_length=100, unique=True)
    issued_date = models.DateField(auto_now_add=True)
    certificate_file = models.FileField(upload_to='certificates/', blank=True, null=True)
    student_name = models.CharField(max_length=255)
    course_name = models.CharField(max_length=255)
    course_duration = models.CharField(max_length=255)
    organization_name = models.CharField(max_length=255, null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table='certificate'
        
    def generate_certificate_number(self, *args, **kwargs):
        prefix = "AYC"
        now = get_ist_now()
        month_year = now.strftime("%m%y")
        like_pattern = f"{prefix}{month_year}"
        existing = Certificate.objects.filter(certificate_number__startswith=like_pattern).count()
        serial = existing + 1
        return f"{prefix}{month_year}{serial:04d}"

    def save(self, *args, **kwargs):
        if not self.certificate_number:
            self.certificate_number = self.generate_certificate_number()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Certificate - {self.student}"

class Announcement(models.Model):
    id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=255)
    content = models.TextField()
    content_pic = models.ImageField(upload_to='announcements/', blank=True, null=True)
    background_pic = models.ImageField(upload_to='announcements/', blank=True, null=True)
    audience = models.CharField(
        max_length=20,
        default="all"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

class Feedback(models.Model):
    student_id = models.CharField(max_length=50)
    student_name = models.CharField(max_length=100)
    trainer_name = models.CharField(max_length=100)
    rating = models.PositiveIntegerField()  # e.g., 1 to 5
    comments = models.TextField()
    suggestions = models.TextField(blank=True, null=True)
    submitted_date = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        db_table = 'feedback'

    def __str__(self):
        return f"{self.student_name} → {self.trainer_name} ({self.rating}/5)"
    
class Test(models.Model):
    test_id = models.AutoField(primary_key=True)
    test_name = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(max_length=255, null=True, blank=True)
    duration = models.CharField(max_length=10, null=True, blank=True)  # in minutes
    total_marks = models.PositiveIntegerField(null=True, blank=True)
    course_id = models.ForeignKey('Course', on_delete=models.CASCADE)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class TestQuestions(models.Model):
    question_id = models.AutoField(primary_key=True)
    test_id = models.ForeignKey(
        Test,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="test_questions"
    )
    question = models.CharField(max_length=255, null=True, blank=True)
    type = models.CharField(max_length=20) #mcq, written
    options = models.JSONField(max_length=255,null=True, blank=True, help_text="MCQ options from frontend")
    marks = models.PositiveBigIntegerField(null=True, blank=True)
    written_answer = models.TextField(null=True, blank=True, help_text="Correct answer for written questions")
    mcq_correct_option = models.CharField(max_length=255, null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.question} ({self.type})"

class StudentAnswers(models.Model):
    answer_id = models.AutoField(primary_key=True)
    student_id = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="student_answers",
        null=True, blank=True
    )
    question_id = models.ForeignKey(TestQuestions, on_delete=models.CASCADE, related_name="student_answers")
    test_id = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="student_test_answers")
    selected_option = models.TextField(null=True, blank=True)
    written_answer = models.TextField(null=True, blank=True)
    is_correct = models.BooleanField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    question_text = models.TextField(null=True, blank=True)
    options_snapshot = models.JSONField(null=True, blank=True)
    correct_answer_snapshot = models.TextField(null=True, blank=True)
    marks_snapshot = models.FloatField(null=True, blank=True)

class TestResult(models.Model):
    result_id = models.AutoField(primary_key=True)
    student_id = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="test_results")
    test_id = models.ForeignKey(Test, on_delete=models.CASCADE, related_name="test_results")
    score = models.PositiveIntegerField(null=True, blank=True)
    time_taken = models.DurationField(null=True, blank=True)
    evaluated_by = models.ForeignKey(
        "Trainer",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="evaluated_results"
    )
    evaluated_at = models.DateTimeField(auto_now=True)

class LeaveRequest(models.Model):
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        to_field='student_id',
        db_column='student_id', null=False
    )
    leave_type = models.CharField(max_length=50)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(max_length=20, default='pending')  # pending, approved, rejected
    applied_on = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        Trainer,
        on_delete=models.SET_NULL,
        null=True,  
        blank=True,
        related_name='leave_requests_reviewed'
    )
    reviewed_on = models.DateTimeField(null=True, blank=True)
    admin_comment = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'leave_request'

    def __str__(self):
        return f"{self.student} - {self.leave_type} ({self.status})"
    
class ClassSchedule(models.Model):
    BUFFER_MINUTES = 0

    schedule_id = models.AutoField(primary_key=True)
    batch = models.ForeignKey('Batch', on_delete=models.CASCADE, related_name='schedules', null=True, blank=True)
    new_batch = models.ForeignKey(
        'NewBatch',
        on_delete=models.CASCADE,
        related_name='schedules',
        null=True, blank=True
    )
    course = models.ForeignKey('Course', on_delete=models.CASCADE)
    trainer = models.ForeignKey('Trainer', on_delete=models.SET_NULL, null=True)
    scheduled_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    duration = models.DurationField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    is_online_class = models.BooleanField(default=False)
    is_class_cancelled = models.BooleanField(default=False)
    actual_end_time = models.DateTimeField(null=True, blank=True)
    meeting_link = models.URLField(max_length=500, null=True, blank=True)
    class_link = models.TextField(max_length=500, null=True, blank=True)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['trainer']),
            models.Index(fields=['course']),
            models.Index(fields=['created_by']),
            models.Index(fields=['created_by_type']),
            models.Index(fields=['scheduled_date']),
            models.Index(fields=['batch']),
            models.Index(fields=['new_batch']),
        ]

    def save(self, *args, **kwargs):
        if self.start_time and self.end_time:
            start_seconds = self.start_time.hour * 3600 + self.start_time.minute * 60 + self.start_time.second
            end_seconds = self.end_time.hour * 3600 + self.end_time.minute * 60 + self.end_time.second
            if end_seconds < start_seconds:
                end_seconds += 24 * 3600
            self.duration = timedelta(seconds=(end_seconds - start_seconds))
        super().save(*args, **kwargs)

    def scheduled_end_datetime(self):
        """Combine scheduled_date and end_time as a timezone-aware datetime."""
        return datetime.datetime.combine(
            self.scheduled_date,
            self.end_time,
            tzinfo=timezone.get_current_timezone()
        )

    def get_extra_time(self):
        if not self.actual_end_time:
            return timedelta(0)

        threshold = self.scheduled_end_datetime() + timedelta(minutes=self.BUFFER_MINUTES)

        if self.actual_end_time > threshold:
            return self.actual_end_time - threshold

        return timedelta(0)

    def get_planned_duration(self):
        """Return the planned class duration (from start_time to end_time)."""
        start_dt = datetime.datetime.combine(
            self.scheduled_date,
            self.start_time,
            tzinfo=timezone.get_current_timezone()
        )
        end_dt = self.scheduled_end_datetime()
        return end_dt - start_dt

    def get_actual_duration(self):
        """Return actual duration (from start_time to actual_end_time)."""
        if not self.actual_end_time:
            return None
        start_dt = datetime.datetime.combine(
            self.scheduled_date,
            self.start_time,
            tzinfo=timezone.get_current_timezone()
        )
        return self.actual_end_time - start_dt

    def __str__(self):
        return f"{self.course.course_name} - {self.scheduled_date} ({self.start_time}-{self.end_time})"

class RecurringSchedule(models.Model):
    recurring_id = models.AutoField(primary_key=True)
    course = models.ForeignKey('Course', on_delete=models.CASCADE)
    batch = models.ForeignKey('Batch', on_delete=models.CASCADE, null=True, blank=True)
    new_batch = models.ForeignKey(
        'NewBatch',
        on_delete=models.CASCADE,
        related_name='recurring_schedules',
        null=True, blank=True
    )
    trainer = models.ForeignKey('Trainer', on_delete=models.CASCADE)

    recurrence_type = models.CharField(max_length=20, null=True, blank=True)
    days_of_week = models.JSONField(null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_online_class = models.BooleanField(default=False)
    class_link = models.TextField(max_length=500, null=True, blank=True)

    country = models.CharField(max_length=5, default="IN")
    subdiv = models.CharField(max_length=10, null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['new_batch']),
        ]
    
    def __str__(self):
        return f"Recurring {self.course.course_name} ({self.recurrence_type})"
      
class Batch(models.Model):
    batch_id = models.AutoField(primary_key=True)
    batch_name = models.CharField(max_length=100)
    title = models.CharField(max_length=100, null=True, blank=True)
    scheduled_date = models.DateField()
    status = models.BooleanField(default=True, null=True, blank=True)
    notes = models.CharField(max_length=255, null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'batch'
        
    def save(self, *args, **kwargs):
        if not self.batch_name:
            year = self.scheduled_date.year if self.scheduled_date else date.today().year
            year_suffix = str(year)[-2:]  # '25' from 2025

            # Count batches in this year
            batches_this_year = Batch.objects.filter(scheduled_date__year=year).count()

            # Determine letter and number
            letter_index = batches_this_year // 999  # every 999 batches rolls to next letter
            sequence_number = (batches_this_year % 999) + 1  # 1–999

            # Get corresponding uppercase letter: A, B, C, etc.
            letters = string.ascii_uppercase
            if letter_index >= len(letters):
                raise ValueError("Batch limit exceeded for the year")

            letter = letters[letter_index]
            batch_code = f"AYA-AKIRA-{year_suffix}{letter}{sequence_number:03d}"
            self.batch_name = batch_code

        super().save(*args, **kwargs)
        
    def deactivate_batch(self, batch):
        IST = timezone.get_current_timezone()  # Or pytz.timezone("Asia/Kolkata") if using IST specifically
        now = timezone.now().astimezone(IST)

        # Step 1: Deactivate the batch
        batch.status = False
        batch.save(update_fields=["status"])

        # Step 2: Archive only upcoming schedules
        schedules_qs = ClassSchedule.objects.filter(
            batch=batch,
            is_archived=False
        )

        schedules_to_archive = []

        for sched in schedules_qs:
            start_time = sched.start_time or time(9, 0)
            end_time = sched.end_time or (sched.start_time or time(9, 0)) + timedelta(hours=1)

            start_dt = datetime.combine(sched.scheduled_date, start_time)
            end_dt = datetime.combine(sched.scheduled_date, end_time)
            start_dt = timezone.make_aware(start_dt, IST)
            end_dt = timezone.make_aware(end_dt, IST)

            if end_dt > now:
                schedules_to_archive.append(sched.schedule_id)

        ClassSchedule.objects.filter(schedule_id__in=schedules_to_archive).update(is_archived=True)

    def __str__(self):
        return f"{self.batch_name}"
    
class BatchCourseTrainer(models.Model):
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='batchcoursetrainer')
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, db_column='student_id')
    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.batch.batch_name}: {self.course.course_name} -> {self.trainer.full_name}"
    
class NewBatch(models.Model):
    batch_id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=100)
    course = models.ForeignKey('Course', on_delete=models.CASCADE, related_name='new_batches')
    trainer = models.ForeignKey('Trainer', on_delete=models.CASCADE, related_name='new_batches')
    start_date = models.DateField()
    end_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    slots = models.PositiveIntegerField(default=0)
    status = models.BooleanField(default=True)
    students = models.ManyToManyField('Student', related_name='new_batches', blank=True)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_archived = models.BooleanField(default=False)

    def available_slots(self):
        return self.slots - self.students.count()
    
    def deactivate_batch(self):
        """
        Deactivate the batch and delete only upcoming schedules.
        Past schedules remain untouched.
        """
        IST = timezone.get_current_timezone()
        now = timezone.now().astimezone(IST)

        # Step 1: Mark this batch as archived / deactivated
        self.is_archived = True
        self.save(update_fields=["is_archived"])

        # Step 2: Get only schedules for this batch
        schedules_qs = ClassSchedule.objects.filter(
            new_batch=self,
            is_archived=False
        )

        upcoming_to_delete = []

        for sched in schedules_qs:
            start_dt = datetime.combine(
                sched.scheduled_date,
                sched.start_time or time(9, 0)
            )
            start_dt = timezone.make_aware(start_dt, IST)

            # Only delete schedules whose start time is in the future
            if start_dt > now:
                upcoming_to_delete.append(sched.schedule_id)

        # Step 3: Delete only future schedules
        ClassSchedule.objects.filter(schedule_id__in=upcoming_to_delete).delete()

    def __str__(self):
        return f"{self.title} ({self.course.course_name})"
    
class Assignment(models.Model):
    id = models.AutoField(primary_key=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=50, default='new', null=True, blank=True)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='assignments', null=True, blank=True)
    assigned_by = models.ForeignKey(Trainer, on_delete=models.SET_NULL, null=True, related_name='created_assignments')
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        course_name = self.course.course_name if self.course else "No Course"
        return f"{self.title} — {course_name}"

class Submission(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name='submissions', null=True, blank=True)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='submissions', null=True, blank=True)
    text = models.TextField(null=True, blank=True)
    status = models.BooleanField(default=True, null=True, blank=True)
    file = models.FileField(upload_to='submission/', null=True, blank=True)
    date = models.DateTimeField(auto_now_add=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.assignment.title} ← {self.student.registration_id}"

class SubmissionReply(models.Model):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name='replies', null=True, blank=True)
    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE, related_name='replies', null=True, blank=True)
    text = models.TextField(null=True, blank=True)
    date = models.DateTimeField(auto_now_add=True)
    is_archived = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Reply to {self.submission.assignment.title} by {self.trainer.full_name}"
    
class Notification(models.Model):
    id = models.AutoField(primary_key=True)
    super_admin = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications")
    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications")
    sub_admin = models.ForeignKey(SubAdmin, on_delete=models.CASCADE, null=True, blank=True)
    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True)
    assignment = models.ForeignKey(Assignment, on_delete=models.SET_NULL, null=True, blank=True)
    test = models.ForeignKey(Test, on_delete=models.SET_NULL, null=True, blank=True)
    topic = models.ForeignKey(Topic, on_delete=models.SET_NULL, null=True, blank=True)
    schedule = models.ForeignKey(ClassSchedule, on_delete=models.SET_NULL, null=True, blank=True)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        target = self.student.registration_id if self.student else self.trainer.employee_id
        return f"Notification → {target}: {self.message[:30]}"

class ChatRoom(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="chat_rooms")
    trainer = models.ForeignKey(Trainer, on_delete=models.CASCADE, related_name="chat_rooms")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("student", "trainer")

    def __str__(self):
        return f"Room: {self.student.registration_id} ↔ {self.trainer.employee_id}"

class Message(models.Model):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="messages")
    sender_type = models.CharField(max_length=20)
    sender_id = models.CharField(max_length=50)
    content = models.TextField(null=True, blank=True)
    upload = models.FileField(upload_to='chat/uploades/', null=True, blank=True)
    audio_file = models.FileField(upload_to="chat/audio/", blank=True, null=True)
    is_read = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.sender_type}({self.sender_id}): {self.content[:20]}"
    
class StudentTicket(models.Model):
    ticket_id = models.AutoField(primary_key=True)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="tickets")
    subject = models.CharField(max_length=255)
    message = models.TextField()
    priority = models.CharField(max_length=10, default="Low")
    status = models.CharField(max_length=20, default="New")  # open / in_progress / closed
    handled_by_trainer = models.ForeignKey(
        Trainer, on_delete=models.SET_NULL, null=True, blank=True, related_name="handled_tickets"
    )
    handled_by_superadmin = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="superadmin_handled_tickets"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    updated_by_id = models.PositiveIntegerField(null=True, blank=True)
    updated_by = GenericForeignKey('updated_by_type', 'updated_by_id')

    def __str__(self):
        return f"Ticket #{self.ticket_id}"

class TicketReply(models.Model):
    reply_id = models.AutoField(primary_key=True)
    ticket = models.ForeignKey(StudentTicket, on_delete=models.CASCADE, related_name="replies")
    student = models.ForeignKey(Student, on_delete=models.SET_NULL, null=True, blank=True)
    trainer = models.ForeignKey(Trainer, on_delete=models.SET_NULL, null=True, blank=True)
    super_admin = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    message = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)


class TicketAttachment(models.Model):
    attachment_id = models.AutoField(primary_key=True)
    ticket = models.ForeignKey(StudentTicket, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to='tickets/')
    created_at = models.DateTimeField(default=timezone.now)

class DeactivationLog(models.Model):
    student = models.ForeignKey('Student', on_delete=models.CASCADE)
    reason = models.CharField(max_length=100)  # after_batch_completion, after_course_completion, custom
    deactivated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student} deactivated for {self.reason} at {self.deactivated_at}"

class UserPresence(models.Model):
    user_type = models.CharField(max_length=20)
    user_id = models.CharField(max_length=50, unique=True)
    is_online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.user_type} {self.user_id} - {'Online' if self.is_online else 'Offline'}"

class UserActivityLog(models.Model):
    user_id = models.CharField(max_length=100,null=True, blank=True)
    username = models.CharField(max_length=100, null=True, blank=True)
    user_type = models.CharField(max_length=20, null=True, blank=True)  # student / tutor / admin
    action = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.username} - {self.action} at {self.timestamp}"

class PasswordResetOTP(models.Model):
    email = models.EmailField()
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=10)
    
class PaymentGateway(models.Model):
    
    gatway_name = models.CharField(max_length=50)
    public_key = models.CharField(max_length=200, blank=True, null=True)
    secret_key = models.CharField(max_length=200, blank=True, null=True)
    webhook_secret = models.CharField(max_length=200, blank=True, null=True)
    currency = models.CharField(max_length=10, blank=True, null=True)
    created_by = models.CharField(max_length=50, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({'Enabled' if self.is_enabled else 'Disabled'})"

class PaymentTransaction(models.Model):

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="transactions", null=True, blank=True)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="course_transactions", null=True, blank=True)

    gateway = models.ForeignKey(PaymentGateway, on_delete=models.SET_NULL, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # ADD THIS
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_after_discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    currency = models.CharField(max_length=10, null=True, blank=True)
    payment_status = models.CharField(max_length=20, null=True, blank=True)
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    order_id = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    metadata = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    def __str__(self):
        return f"{self.student} - {self.amount} {self.currency} ({self.payment_status})"


class PaymentLog(models.Model):
    transaction = models.ForeignKey(PaymentTransaction, on_delete=models.CASCADE, related_name="logs")
    event_type = models.CharField(max_length=100)
    payload = models.JSONField(blank=True, null=True)
    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Log for {self.transaction.transaction_id} ({self.event_type})"

class PaymentEMI(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="emi_plans")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="emi_plans", null=True, blank=True)

    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    months = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return f"{self.student.student_id} - {self.months} months"
    
    def create_installments(self):
        from datetime import date, timedelta

        monthly_amount = self.total_amount / self.months
        today = date.today()

        installments = []
        for i in range(self.months):
            due_date = today + timedelta(days=30 * (i + 1))
            installments.append(
                PaymentEMIInstallment(
                    emi_plan=self,
                    course=self.course,                 # NEW IMPORTANT LINE
                    amount=monthly_amount,
                    due_date=due_date
                )
            )

        PaymentEMIInstallment.objects.bulk_create(installments)
        return installments


class PaymentEMIInstallment(models.Model):
    emi_plan = models.ForeignKey(PaymentEMI, on_delete=models.CASCADE, related_name="installments")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, null=True, blank=True)

    due_date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid = models.BooleanField(default=False)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    payment = models.ForeignKey(PaymentTransaction, on_delete=models.SET_NULL, null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)


    def __str__(self):
        return f"Installment for {self.emi_plan.student.student_id} - {self.amount}"

class Lead(models.Model):
    name = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=15)
    email = models.EmailField(blank=True, null=True)
    interested = models.BooleanField(default=True)
    course = models.CharField(max_length=100, blank=True, null=True)
    followup_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    followup_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=50, default='new')
    notes = models.TextField(blank=True, null=True)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.name or 'Unknown'} - {self.phone}"
    
class LeadCallLog(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="call_logs")
    called_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    call_time = models.DateTimeField(auto_now_add=True)
    call_status = models.CharField(max_length=50, blank=True, null=True)  # e.g., 'answered', 'missed'

    def __str__(self):
        return f"Call with {self.called_by} on {self.call_time}"
    
