from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models
from django.utils import timezone
from django.contrib.postgres.fields import ArrayField
from datetime import timedelta
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from rest_framework.exceptions import ValidationError
import pytz
import uuid
from batches.models import ClassSchedule, NewBatch, Batch
from courses.models import Course
from webinar.models import WebinarRegistration



def validate_image_or_svg(file):
    if not file.name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg')):
        raise ValidationError('Unsupported file type.')

class Settings(models.Model):
    company_name = models.CharField(max_length=100, null=True, blank=True)
    company_address = models.CharField(max_length=255, null=True, blank=True)
    company_contact = models.CharField(max_length=100, null=True, blank=True)
    company_email = models.CharField(max_length=100, null=True, blank=True)
    company_website = models.CharField(max_length=100, null=True, blank=True)
    bank_name = models.CharField(max_length=100, null=True, blank=True)
    acc_name = models.CharField(max_length=255, null=True, blank=True)
    bank_branch = models.CharField(max_length=100, null=True, blank=True)
    bank_account_no = models.CharField(max_length=100, null=True, blank=True)
    bank_ifsc = models.CharField(max_length=100, null=True, blank=True)
    upi_id = models.CharField(max_length=100, null=True, blank=True)
    general_logo = models.FileField(upload_to='logos/', null=True, blank=True, validators=[validate_image_or_svg])
    secondary_logo = models.FileField(upload_to='logos/', null=True, blank=True, validators=[validate_image_or_svg])
    email_logo = models.FileField(upload_to='logos/', null=True, blank=True, validators=[validate_image_or_svg])
    signature = models.FileField(upload_to='signatures/', null=True, blank=True, validators=[validate_image_or_svg])
    gst_detail = models.CharField(max_length=100, null=True, blank=True)
    declaration = models.TextField(max_length=500, null=True, blank=True)
    attendance_options = models.CharField(max_length=100, null=True, blank=True)
    deactivation_options = models.CharField(max_length=100, null=True, blank=True)
    payment_method = models.JSONField(default=list, blank=True)
    stripe_enabled = models.BooleanField(default=True)
    paypal_enabled = models.BooleanField(default=True)
    razorpay_enabled=models.BooleanField(default=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    gst_number = models.CharField(max_length=50, null=True, blank=True)
    cgst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=9)
    sgst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=9)
    igst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=18)
    DATE_FORMAT_CHOICES = [("DD-MM-YYYY", "DD-MM-YYYY"),("MM-DD-YYYY", "MM-DD-YYYY"),("YYYY-MM-DD", "YYYY-MM-DD"),("DD/MM/YYYY", "DD/MM/YYYY"),("DD/MM/YY","DD/MM/YY")]
    TIME_FORMAT_CHOICES = [("12", "12 Hours"),("24", "24 Hours"),]
    PHONE_FORMAT_CHOICES = [("INDIA", "India (+91)"),("US", "US (+1)"),("RAW", "Raw Number"),]
    date_format = models.CharField(max_length=20,choices=DATE_FORMAT_CHOICES,default="DD-MM-YYYY")
    time_format = models.CharField(max_length=10,choices=TIME_FORMAT_CHOICES,default="24")
    phone_format = models.CharField(max_length=20,choices=PHONE_FORMAT_CHOICES,default="INDIA")


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
    status = models.CharField(max_length=255, null=True, blank=True)

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
    status=models.BooleanField(default=True)

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
    username = models.CharField(max_length=50, null=True, blank=True)
    password = models.CharField(max_length=128, null=False, blank=False)
    full_name = models.CharField(max_length=255, db_index=True)
    user_type = models.CharField(max_length=20, null=False, blank=False, db_index=True)
    tutor_type = models.CharField(max_length=50,null= True,blank =True)     #part time or full time
    dob = models.DateField(null=True, blank=True)

    address = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=50,null= True,blank =True)
    state = models.CharField(max_length=50,null= True,blank =True)
    country = models.CharField(max_length=255, null=True, blank=True)
    pincode = models.IntegerField(null=True, blank=True)
    profile_pic = models.ImageField(upload_to=trainer_profile_pic_path, null=True, blank=True)
    email = models.EmailField()
    contact_no = models.CharField(max_length=20)

    salary = models.FloatField(null=True, blank=True)
    salary_type = models.CharField(max_length=255, null=True, blank=True)
    courses = models.ManyToManyField(Course, related_name='trainer_courses', blank=True)
    
    gender = models.CharField(max_length=10, null=True, blank=True)
    specialization = models.CharField(max_length=255, null=True, blank=True)
    working_hours = models.CharField(max_length=100, null=True, blank=True)
    
    experience = models.CharField(max_length=20, null=True, blank=True) 
    last_company = models.CharField(max_length=255, null=True, blank=True)
    linkedin_profile = models.CharField(max_length=100, null=True, blank=True)
    short_bio = models.CharField(max_length=200, null=True, blank=True)
    joining_date = models.DateField(null=True, blank=True)

    account_no = models.BigIntegerField(null=True, blank=True)
    account_holder_name = models.CharField(null=True, blank=True)
    bank_name = models.CharField(null=True, blank=True)
    ifsc_code = models.CharField(max_length=20,null=True, blank=True)
    upi_id = models.CharField(null=True, blank=True)
    gpay_no = models.BigIntegerField(null=True, blank=True)

    aadhar_card = models.FileField(upload_to="trainers_data/adharcard",null=True, blank=True)
    pan_card = models.FileField(upload_to="trainers_data/pancard",null=True, blank=True)
    resume= models.FileField(upload_to="trainers_data/resume",null=True, blank=True)
    certificate = models.FileField(upload_to="trainers_data/certificate",null=True, blank=True)
    photo = models.FileField(upload_to="trainers_data/photo",null=True, blank=True)

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

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower()  # force lowercase before saving
        if not self.employee_id:
            self.employee_id = self.generate_employee_id()
        super().save(*args, **kwargs)

    def generate_employee_id(self):
        prefix = "AA-TUT"
        current_date = get_ist_now()
        month = current_date.strftime("%m")
        year = current_date.strftime("%y")

        from .models import Trainer  # avoid circular import
        trainers = Trainer.objects.filter(employee_id__contains=f"{month}{year}")
        count = trainers.count() + 1 
        number = (count - 1) % 999 + 1
        return f"{prefix}-{month}{year}-{number:03d}"

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
        NewBatch,
        on_delete=models.CASCADE,
        null=True,
        related_name='trainer_attendance'
    )
    schedule_id = models.ForeignKey(
        ClassSchedule,
        on_delete=models.CASCADE,
        null=True, blank=True
    )
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.SET_NULL)
    date = models.DateTimeField(null=False, blank=False)
    status = models.CharField(max_length=10)
    course =models.ForeignKey(Course, on_delete=models.CASCADE, null=False, blank=False)
    topic = models.TextField(blank=True)
    sub_topic = models.TextField(blank=True)
    marked_by_admin = models.BooleanField(default=False)

    class Meta:
        db_table = 'trainer_attendance'


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
    last_name = models.CharField(max_length=255, null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    gender = models.CharField(max_length=255, null=True, blank=True)
    discount = models.DecimalField(max_digits=10, decimal_places=2, null =True)
    dob = models.DateField()
    email = models.EmailField( null=False, blank=False)
    contact_no = models.CharField(max_length=20, null=False, blank=False)
    alternate_mobile_no = models.CharField(max_length=20, null=True, blank=True)
    current_address = models.TextField(max_length=255, null=False, blank=False)
    permanent_address = models.TextField(max_length=255, null=False, blank=False)
    joining_date = models.DateField(auto_now_add=True)
    internship_required = models.BooleanField(default=False)
    internship = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=255, null=False, blank=False)
    state = models.CharField(max_length=255, null=False, blank=False)
    country = models.CharField(max_length=255, null=False, blank=False) 
    parent_guardian_name = models.CharField(max_length=255, null=True, blank=True)
    parent_guardian_phone = models.CharField(max_length=20, null=True, blank=True)
    parent_guardian_occupation = models.CharField(max_length=255, null=True, blank=True)
    trainer = models.ForeignKey(Trainer, on_delete=models.SET_NULL, null=True, blank=True, related_name='students')
    is_referenced = models.BooleanField(default=False)
    reference_name = models.CharField(max_length=255, null=True, blank=True)
    reference_number = models.CharField(max_length=255, null=True, blank=True)
    student_type = models.CharField(max_length=30, null=False, blank=False)
    source_type = models.CharField(max_length=255,null=True,blank=False)
    source_name = models.CharField(max_length = 250,null = True,blank=False)
    status = models.BooleanField(default=True, null=False, blank=False)
    converter = models.CharField(default = True,null = False,blank = False)
    notes = GenericRelation("Note", related_query_name="student_notes")
    created_by = models.CharField(max_length=100, null=True, blank=True)
    created_by_type = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    payment_mode = models.CharField(max_length = 150 , blank=True,null= True)
    stu_gst_number = models.CharField(max_length=50, null = True, blank=True)

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

class Studentusertype(models.Model):
    student = models.ForeignKey(Student, on_delete=models.SET_NULL, null=True)
    user_type = models.CharField(null = True ,blank = True)
    is_active = models.BooleanField(default=True, null=False, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)

class Studentsubusertype(models.Model):
    student = models.ForeignKey(Student, on_delete=models.SET_NULL, null=True)
    user_type = models.CharField(null = True,blank = True)
    name = models.CharField(null = True, blank=True)
    is_active = models.BooleanField(default=True, null=False, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)

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
    gst_number = models.CharField(max_length=50, null=True, blank=True)

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

    company = models.ForeignKey(
        Employer,
        on_delete=models.CASCADE,
        related_name='sub_admins'
    )

    employer_id = models.AutoField(primary_key=True)

    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True)

    full_name = models.CharField(max_length=255)

    email = models.EmailField(null=True, blank=True)

    phone_no = models.CharField(max_length=14, null=True, blank=True)

    username = models.CharField(max_length=50)

    password = models.CharField(max_length=128)

    designation = models.CharField(
        max_length=50,
        default="sub_admin",
        null=True,
        blank=True
    )

    status = models.BooleanField(default=True, null=True, blank=True)

    notes = models.CharField(max_length=255, null=True, blank=True)

    is_archived = models.BooleanField(default=False)

    created_by = models.CharField(max_length=100, null=True, blank=True)

    created_by_type = models.CharField(max_length=50, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def id(self):
        return self.employer_id

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
        ClassSchedule,
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
        NewBatch,
        on_delete=models.CASCADE,
        null=True,
        related_name='attendance'
    )
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.SET_NULL)
    date = models.DateTimeField(null=False, blank=False)
    status = models.CharField(max_length=10)
    ip_address= models.GenericIPAddressField(null=True, blank=True)
    marked_by_admin = models.BooleanField(default=False)

    class Meta:
        db_table = 'attendance'
        indexes = [
            models.Index(fields=["student", "date"]),
            models.Index(fields=["status"])
        ]
    
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
        db_column='student_id', null=True, blank=True
    )
    webinar_registration = models.OneToOneField(
        'webinar.WebinarRegistration',
        on_delete=models.CASCADE,   
        null=True, blank=True,
        related_name='certificate'
    )
    # on_delete=models.CASCADE, 
    # related_name='certificate',null=True,blank=True
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
  
class StudentTicket(models.Model):
    ticket_id = models.AutoField(primary_key=True)

    ticket_token = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="tickets", null=True, blank=True)
    webinar_participant = models.ForeignKey(
        WebinarRegistration, on_delete=models.CASCADE, null=True, blank=True
    )
    name = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    ticket_type = models.CharField(max_length=30,default="support") # support / course enquiry / etc....(ithukumela therila later will add)
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
    
 

