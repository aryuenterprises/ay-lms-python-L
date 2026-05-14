from celery import shared_task

from payments.services.invoice_service import InvoiceService
from payments.services.email_service import PaymentEmailService


@shared_task
def generate_and_send_invoice(transaction_id):

    transaction = InvoiceService.generate_invoice(transaction_id)

    PaymentEmailService.send_invoice_email(transaction)