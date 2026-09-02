import logging
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from datetime import datetime
from django.utils import timezone

logger = logging.getLogger(__name__)


def send_webinar_registration_email(registration):
    webinar = registration.webinar
    ist_time = timezone.localtime(webinar.scheduled_start)
    subject = f"Registration Confirmed: {webinar.title}"
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://aylms.aryuprojects.com')

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin:0; padding:0; background-color:#f5f6fa; font-family:Arial, Helvetica, sans-serif;">

      <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f6fa; padding:40px 0;">
        <tr>
          <td align="center">
            <table width="520" cellpadding="0" cellspacing="0" style="background:#ffffff; border-radius:10px; box-shadow:0 2px 8px rgba(0,0,0,0.08);">

              <!-- Header -->
              <tr>
                <td style="background:#852121; padding:20px; border-radius:10px 10px 0 0; text-align:center;">
                  <h2 style="color:#ffffff; margin:0; font-size:20px;">
                    Webinar Registration Confirmed
                  </h2>
                </td>
              </tr>

              <!-- Body -->
              <tr>
                <td style="padding:30px; color:#333333; font-size:14px; line-height:1.6;">
                  <p>Hello <strong>{registration.name}</strong>,</p>
                  <p>Thank you for registering for the webinar <strong>"{webinar.title}"</strong>. Here are the details:</p>

                  <table width="100%" cellpadding="5" cellspacing="0" style="font-size:13px; margin:20px 0; border:1px solid #eeeeee; padding:10px; border-radius:6px;">
                    <tr>
                      <td width="30%" style="font-weight:bold; color:#666;">Date:</td>
                      <td>{ist_time.strftime("%A, %B %d, %Y")}</td>
                    </tr>
                    <tr>
                      <td style="font-weight:bold; color:#666;">Time:</td>
                      <td>{ist_time.strftime("%I:%M %p IST")}</td>
                    </tr>
                    <tr>
                      <td style="font-weight:bold; color:#666;">Platform:</td>
                      <td>Online / Google Meet</td>
                    </tr>
                  </table>

                  <p>A calendar invite with the join link will be sent to you shortly before the session.</p>

                  <p style="margin-top:30px;">See you there!</p>
                  <p>Regards,<br>Aryu Academy Team</p>
                </td>
              </tr>

            </table>

            <!-- Footer -->
            <table width="520" cellpadding="0" cellspacing="0">
              <tr>
                <td align="center" style="padding:15px; font-size:12px; color:#999999;">
                  © {webinar.scheduled_start.year} Aryu Academy. All rights reserved.
                </td>

                <hr style="margin:25px 0; border:none; border-top:1px solid #eeeeee;">

                <p style="font-size:12px; color:#777777; line-height:1.5;">
                  By participating in this webinar, you agree to our
                  <a href="https://aylms.aryuprojects.com/terms-and-conditions" style="color:#0d6efd; text-decoration:none;">
                    Terms & Conditions
                  </a>
                  and
                  <a href="https://aylms.aryuprojects.com/privacy-policy" style="color:#0d6efd; text-decoration:none;">
                    Privacy Policy
                  </a>.
                </p>
              </tr>
            </table>

          </td>
        </tr>
      </table>

    </body>
    </html>
    """

    email_msg = EmailMultiAlternatives(
        subject=subject,
        body="Your webinar registration has been confirmed.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[registration.email],
    )
    email_msg.attach_alternative(html_content, "text/html")
    email_msg.send(fail_silently=False)


def send_webinar_certificate_email(registration, certificate_file):
    webinar = registration.webinar
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://aylms.aryuprojects.com')

    subject = f"Certificate of Completion - {webinar.title}"
    from_email = settings.DEFAULT_FROM_EMAIL
    to = [registration.email]

    # Plain text fallback (important for deliverability)
    text_content = f"""
Hi {registration.name or 'Participant'},

Thank you for attending the webinar "{webinar.title}".

Your Certificate of Completion is attached as a PDF.

We appreciate your participation.

Regards,
Aryu Academy
"""

    # HTML version
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin:0; padding:0; background-color:#f5f6fa; font-family:Arial, Helvetica, sans-serif;">

      <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f6fa; padding:40px 0;">
        <tr>
          <td align="center">

            <table width="520" cellpadding="0" cellspacing="0" style="background:#ffffff; border-radius:10px; box-shadow:0 2px 8px rgba(0,0,0,0.08);">
              <tr>
                <td height="20" style="font-size:0; line-height:0;">&nbsp;</td>
              </tr>
              <tr>
                <td style="padding:0 30px; text-align:center;">
                  <h2 style="color:#781b0d; margin:0 0 10px; font-size:22px;">Congratulations!</h2>
                  <p style="color:#333333; font-size:14px; line-height:1.5;">
                    Here is your Certificate of Completion for attending:
                  </p>
                  <p style="color:#781b0d; font-size:16px; font-weight:bold; margin:15px 0;">
                    {webinar.title}
                  </p>
                </td>
              </tr>
              <tr>
                <td height="20" style="font-size:0; line-height:0;">&nbsp;</td>
              </tr>
            </table>

            <!-- Footer -->
            <table width="520" cellpadding="0" cellspacing="0">
              <tr>
                <td align="center" style="padding:15px; font-size:12px; color:#999999;">
                  © {webinar.scheduled_start.year if webinar.scheduled_start else ''} Aryu Academy. All rights reserved.
                </td>


                  <hr style="margin:25px 0; border:none; border-top:1px solid #eeeeee;">

                  <p style="font-size:12px; color:#777777; line-height:1.5;">
                    By accepting this certificate, you agree to our
                    <a href="https://aylms.aryuprojects.com/terms-and-conditions" style="color:#781b0d; text-decoration:none;">
                      Terms & Conditions
                    </a>
                    and
                    <a href="https://aylms.aryuprojects.com/privacy-policy" style="color:#781b0d; text-decoration:none;">
                      Privacy Policy
                    </a>.
                  </p>
              </tr>
            </table>

          </td>
        </tr>
      </table>

    </body>
    </html>
    """

    email_msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=from_email,
        to=to
    )

    email_msg.attach_alternative(html_content, "text/html")

    # Attach certificate PDF safely
    if certificate_file and hasattr(certificate_file, "path"):
        email_msg.attach_file(certificate_file.path)

    email_msg.send(fail_silently=False)


def generate_invoice_pdf(student_name, student_email, student_phone, transaction_id, razorpay_payment_id, course_name, subtotal_str, amount_str, payment_date):
    from weasyprint import HTML
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <style>
        @page {{
            size: A4;
            margin: 20mm;
        }}
        body {{
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            color: #333;
            margin: 0;
            line-height: 1.5;
        }}
        .header {{
            border-bottom: 2px solid #852121;
            padding-bottom: 15px;
            margin-bottom: 25px;
        }}
        .header-table {{
            width: 100%;
        }}
        .logo {{
            font-size: 26px;
            font-weight: bold;
            color: #852121;
        }}
        .invoice-title {{
            font-size: 20px;
            text-align: right;
            color: #555;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .details-table {{
            width: 100%;
            margin-bottom: 30px;
        }}
        .details-table td {{
            vertical-align: top;
            width: 50%;
            font-size: 13px;
        }}
        .section-title {{
            font-size: 14px;
            font-weight: bold;
            color: #852121;
            margin-bottom: 8px;
            border-bottom: 1px solid #ddd;
            padding-bottom: 4px;
            text-transform: uppercase;
        }}
        .items-table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 35px;
        }}
        .items-table th {{
            background-color: #852121;
            color: #fff;
            text-align: left;
            padding: 8px 10px;
            font-size: 13px;
        }}
        .items-table td {{
            padding: 10px;
            border-bottom: 1px solid #eee;
            font-size: 13px;
        }}
        .totals-table {{
            width: 45%;
            margin-left: auto;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        .totals-table td {{
            padding: 6px 10px;
            font-size: 13px;
        }}
        .totals-table .grand-total {{
            font-weight: bold;
            font-size: 15px;
            color: #852121;
            border-top: 1px solid #ddd;
            border-bottom: 2px double #852121;
        }}
        .footer {{
            margin-top: 80px;
            border-top: 1px solid #eee;
            padding-top: 15px;
            text-align: center;
            font-size: 11px;
            color: #777;
        }}
    </style>
    </head>
    <body>
        <div class="header">
            <table class="header-table">
                <tr>
                    <td class="logo">Aryu LMS</td>
                    <td class="invoice-title">Payment Receipt</td>
                </tr>
            </table>
        </div>

        <table class="details-table">
            <tr>
                <td>
                    <div class="section-title">Billed To</div>
                    <strong>Name:</strong> {student_name}<br>
                    <strong>Email:</strong> {student_email}<br>
                    <strong>Phone:</strong> {student_phone or 'N/A'}<br>
                </td>
                <td style="padding-left: 40px;">
                    <div class="section-title">Receipt Details</div>
                    <strong>Date:</strong> {payment_date}<br>
                    <strong>Transaction ID:</strong> {transaction_id or 'N/A'}<br>
                    <strong>Razorpay Payment ID:</strong> {razorpay_payment_id}<br>
                    <strong>Billing Type:</strong> Bootcamp / Webinar<br>
                </td>
            </tr>
        </table>

        <table class="items-table">
            <thead>
                <tr>
                    <th>Description</th>
                    <th style="text-align: right; width: 120px;">Amount</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>{course_name} Enrollment Fee</td>
                    <td style="text-align: right;">{subtotal_str}</td>
                </tr>
            </tbody>
        </table>

        <table class="totals-table">
            <tr>
                <td>Subtotal:</td>
                <td style="text-align: right;">{subtotal_str}</td>
            </tr>
            <tr>
                <td>Tax / GST (0%):</td>
                <td style="text-align: right;">₹0.00</td>
            </tr>
            <tr class="grand-total">
                <td>Total Paid:</td>
                <td style="text-align: right;">{amount_str}</td>
            </tr>
            <tr>
                <td colspan="2" style="text-align: right; color: green; font-weight: bold; padding-top: 12px; font-size: 14px;">STATUS: PAID</td>
            </tr>
        </table>

        <div style="clear: both;"></div>

        <div class="footer">
            Thank you for your enrollment with Aryu LMS!<br>
            For any queries, contact support at support@aryuacademy.com or call 8122869706.
        </div>
    </body>
    </html>
    """
    return HTML(string=html_content).write_pdf()


def send_student_credentials_email(student, password=None, transaction_id=None):
    from django.core.mail import EmailMultiAlternatives
    from django.conf import settings
    from payments.models import PaymentTransaction
    
    subject = "Welcome to Aryu LMS - Registration & Invoice Receipt"
    from_email = settings.DEFAULT_FROM_EMAIL
    to = [student.email]
    
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://portal.aryuacademy.com')
    if not frontend_url or "portal.aryuacademy.com" in frontend_url:
        frontend_url = "https://portal.aryuacademy.com"
        
    login_url = frontend_url
    password_str = password if password else "[Your Existing Password]"
    
    student_name = f"{student.first_name} {student.last_name}".strip() or student.username
    
    # Retrieve transaction details if available
    txn = None
    if transaction_id:
        try:
            txn = PaymentTransaction.objects.get(id=transaction_id)
        except Exception:
            try:
                txn = PaymentTransaction.objects.get(transaction_id=transaction_id)
            except Exception:
                pass

    amount_val = 499.00
    if txn:
        try:
            amount_val = float(txn.amount)
        except (ValueError, TypeError):
            pass
            
    amount_str = f"₹{amount_val:.2f}"
    subtotal_str = f"₹{amount_val:.2f}"
    
    payment_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    razorpay_payment_id = "N/A"
    course_name = "N/A"
    schedule_details = "N/A"
    
    if txn:
        if txn.created_at:
            payment_date = txn.created_at.strftime("%Y-%m-%d %H:%M:%S")
        razorpay_payment_id = txn.transaction_id or (txn.metadata or {}).get("razorpay_payment_id") or "N/A"
        
        if txn.course:
            course_name = txn.course.course_name
        elif txn.metadata and "webinar_id" in txn.metadata:
            from webinar.models import Webinar
            try:
                web = Webinar.objects.get(uuid=txn.metadata["webinar_id"])
                course_name = web.title
                if web.scheduled_start:
                    schedule_details = web.scheduled_start.strftime("%Y-%m-%d %H:%M UTC")
            except Exception:
                pass
                
    if course_name == "N/A":
        from aryuapp.models import StudentCourse
        latest_sc = StudentCourse.objects.filter(student=student).order_by("-id").first()
        if latest_sc:
            course_name = latest_sc.course.course_name

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin:0; padding:0; background-color:#f5f6fa; font-family:Arial, Helvetica, sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f6fa; padding:40px 0;">
        <tr>
          <td align="center">
            <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff; border-radius:10px; box-shadow:0 2px 8px rgba(0,0,0,0.08);">
              <tr>
                <td style="background:#852121; padding:20px; border-radius:10px 10px 0 0; text-align:center;">
                  <h2 style="color:#ffffff; margin:0; font-size:20px;">Welcome to Aryu Academy</h2>
                </td>
              </tr>
              <tr>
                <td style="padding:30px; color:#333333; font-size:14px; line-height:1.6;">
                  <p>Hello <strong>{student_name}</strong>,</p>
                  <p>Your account has been successfully provisioned. Here are your credentials to log in to our portal:</p>
                  
                  <div style="background:#f8f9fa; padding:15px; border-radius:6px; margin-bottom:20px; border-left:4px solid #852121;">
                    <p style="margin:0 0 8px;"><strong>Portal URL:</strong> <a href="{login_url}" style="color:#852121; text-decoration:none; font-weight:bold;">{login_url}</a></p>
                    <p style="margin:0 0 8px;"><strong>Username / Registered Email:</strong> {student.email or student.username}</p>
                    <p style="margin:0;"><strong>Password:</strong> {password_str}</p>
                  </div>
                  
                  <h3 style="color:#852121; border-bottom:1px solid #eee; padding-bottom:8px; margin-top:25px;">Course Enrollment Details</h3>
                  <table width="100%" cellpadding="5" cellspacing="0" style="font-size:13px; margin-bottom:20px;">
                    <tr>
                      <td width="30%" style="font-weight:bold; color:#666;">Course Name:</td>
                      <td>{course_name}</td>
                    </tr>
                    <tr>
                      <td style="font-weight:bold; color:#666;">Schedule Details:</td>
                      <td>{schedule_details}</td>
                    </tr>
                  </table>
                  
                  <h3 style="color:#852121; border-bottom:1px solid #eee; padding-bottom:8px; margin-top:25px;">Payment Invoice / Receipt</h3>
                  <table width="100%" cellpadding="5" cellspacing="0" style="font-size:13px;">
                    <tr>
                      <td width="30%" style="font-weight:bold; color:#666;">Transaction ID:</td>
                      <td>{transaction_id or "N/A"}</td>
                    </tr>
                    <tr>
                      <td style="font-weight:bold; color:#666;">Razorpay Payment ID:</td>
                      <td>{razorpay_payment_id}</td>
                    </tr>
                    <tr>
                      <td style="font-weight:bold; color:#666;">Amount Paid:</td>
                      <td><strong>{amount_str}</strong></td>
                    </tr>
                    <tr>
                      <td style="font-weight:bold; color:#666;">Payment Date:</td>
                      <td>{payment_date}</td>
                    </tr>
                  </table>
                  
                  <p style="margin-top:30px;">We are excited to have you on board.</p>
                  <p>Regards,<br>Aryu Academy Team</p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """
    
    email_msg = EmailMultiAlternatives(
        subject=subject,
        body=(
            f"Welcome to Aryu LMS!\n\n"
            f"Your account has been successfully provisioned. Here are your credentials to log in to our portal:\n\n"
            f"Portal URL: {login_url}\n"
            f"Username / Registered Email: {student.email or student.username}\n"
            f"Password: {password_str}\n\n"
            f"Course Name: {course_name}\n\n"
            f"Payment Invoice Details:\n"
            f"- Transaction ID: {transaction_id or 'N/A'}\n"
            f"- Razorpay Payment ID: {razorpay_payment_id}\n"
            f"- Amount Paid: {amount_str}\n"
            f"- Payment Date: {payment_date}\n"
        ),
        from_email=from_email,
        to=to,
    )
    email_msg.attach_alternative(html_content, "text/html")
    
    # Generate and attach the PDF invoice dynamically
    try:
        pdf_bytes = generate_invoice_pdf(
            student_name=student_name,
            student_email=student.email or student.username,
            student_phone=student.contact_no,
            transaction_id=transaction_id,
            razorpay_payment_id=razorpay_payment_id,
            course_name=course_name,
            subtotal_str=subtotal_str,
            amount_str=amount_str,
            payment_date=payment_date
        )
        if pdf_bytes:
            filename = f"Invoice_{transaction_id}.pdf" if transaction_id else "Invoice_receipt.pdf"
            email_msg.attach(filename, pdf_bytes, "application/pdf")
    except Exception as e:
        logger.exception("Failed to attach PDF invoice to welcome email: %s", e)

    email_msg.send(fail_silently=False)


