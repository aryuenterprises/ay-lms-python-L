from django.db import models
from django.contrib.contenttypes.fields import GenericRelation
# Create your models here.

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

    class Meta:
        db_table = 'aryuapp_paymentgateway'

    def __str__(self):
        return f"{self.gatway_name} ({'Enabled' if not self.is_archived else 'Disabled'})"

class PaymentTransaction(models.Model):

    student = models.ForeignKey("aryuapp.Student", on_delete=models.CASCADE, related_name="transactions", null=True, blank=True)
    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="course_transactions", null=True, blank=True)
    course_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    gateway = models.ForeignKey(PaymentGateway, on_delete=models.SET_NULL, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # ADD THIS
    discount = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    total_after_discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, null=True, blank=True)
    payment_status = models.CharField(max_length=255, null=True, blank=True)
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    payment_mode = models.CharField(max_length=150,blank = True, null = True)
    attachment = models.FileField(upload_to='payment_attachments/', blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    metadata = models.JSONField(blank=True, null=True)
    notes = GenericRelation("aryuapp.Note", related_query_name="payment_notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["student"]),
            models.Index(fields=["course"]),
            models.Index(fields=["id"]),
        ]
        db_table = 'aryuapp_paymenttransaction'


    def __str__(self):
        return f"{self.student} - {self.amount} {self.currency} ({self.payment_status})"


class PaymentLog(models.Model):
    transaction = models.ForeignKey(PaymentTransaction, on_delete=models.CASCADE, related_name="logs")
    event_type = models.CharField(max_length=100)
    payload = models.JSONField(blank=True, null=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'aryuapp_paymentlog'

    def __str__(self):
        return f"Log for {self.transaction.transaction_id} ({self.event_type})"

class PaymentEMI(models.Model):
    student = models.ForeignKey("aryuapp.Student", on_delete=models.CASCADE, related_name="emi_plans")
    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="emi_plans", null=True, blank=True)

    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    months = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'aryuapp_paymentemi'

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
    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE, null=True, blank=True)

    due_date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid = models.BooleanField(default=False)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    payment = models.ForeignKey(PaymentTransaction, on_delete=models.SET_NULL, null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'aryuapp_paymentemiinstallment'


    def __str__(self):
        return f"Installment for {self.emi_plan.student.student_id} - {self.amount}"
