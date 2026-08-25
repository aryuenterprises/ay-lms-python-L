from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from datetime import datetime
from django.utils import timezone


def send_webinar_registration_email(registration):
    webinar = registration.webinar
    ist_time = timezone.localtime(webinar.scheduled_start)
    subject = f"Registration Confirmed: {webinar.title}"

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

                  <p style="margin:0 0 15px;">
                    Hello <strong>{registration.name}</strong>,
                  </p>

                  <p style="margin:0 0 15px;">
                    Thank you for registering for the following webinar:
                  </p>

                  <div style="background:#f8f9fa; padding:15px; border-radius:6px; margin-bottom:20px;">
                    <p style="margin:0 0 8px;"><strong>{webinar.title}</strong></p>
                    <p style="margin:0;">
                      <strong>Date:</strong> {ist_time.strftime('%d %b %Y')}<br>
                      <strong>Time:</strong> {ist_time.strftime('%I:%M %p')}
                    </p>
                  </div>

                  <p style="margin:0 0 10px; font-size:14px; color:#555;">
                    Join our WhatsApp group to receive important updates, reminders, and session materials related to the webinar.
                  </p>

                  <p style="word-break:break-all; color:#2b9627;">
                    <a href="{ webinar.waba_link }" style="color:#44a65c; text-decoration:none;">
                      { webinar.waba_link }
                    </a>
                  </p>

                  <p style="margin-top:25px;">
                    We look forward to your participation.
                  </p>

                  <p style="margin-top:30px; font-size:13px; color:#888888;">
                    Regards,<br>
                    Aryu Academy
                  </p>

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
              <!-- Header -->
              <tr>
                <td style="background:#781b0d; padding:20px; border-radius:10px 10px 0 0; text-align:center;">
                  <h2 style="color:#ffffff; margin:0; font-size:20px;">
                    Certificate of Completion 
                  </h2>
                </td>
              </tr>

              <!-- Body -->
              <tr>
                <td style="padding:30px; color:#333333; font-size:14px; line-height:1.6;">

                  <p style="margin:0 0 15px;">
                    Hello <strong>{registration.name or 'Participant'}</strong>,
                  </p>

                  <p style="margin:0 0 15px;">
                    Thank you for successfully attending the webinar:
                  </p>

                  <div style="background:#f8f9fa; padding:15px; border-radius:6px; margin-bottom:20px;">
                    <p style="margin:0; font-weight:bold;">
                      {webinar.title}
                    </p>
                  </div>

                  <p style="margin:0 0 15px;">
                    Your Certificate of Completion is attached to this email as a PDF file.
                  </p>

                  <p style="margin:0 0 15px;">
                    We appreciate your participation and look forward to seeing you in future sessions.
                  </p>


                  <p style="margin-top:30px; font-size:13px; color:#888888;">
                    Regards,<br>
                    Aryu Academy
                  </p>

                </td>
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


def send_student_credentials_email(student, password=None, transaction_id=None):
    from django.core.mail import EmailMultiAlternatives
    from django.conf import settings
    from payments.models import PaymentTransaction
    
    subject = "Welcome to Aryu Academy - Onboarding Credentials & Receipt"
    from_email = settings.DEFAULT_FROM_EMAIL
    to = [student.email]
    
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://aylms.aryuprojects.com')
    if not frontend_url or "portal.aryuacademy.com" in frontend_url:
        frontend_url = "https://aylms.aryuprojects.com"
        
    login_url = f"{frontend_url}/login"
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

    amount_str = "N/A"
    payment_date = "N/A"
    razorpay_payment_id = "N/A"
    course_name = "N/A"
    schedule_details = "N/A"
    
    if txn:
        amount_str = f"INR {txn.amount}"
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
                    <p style="margin:0 0 8px;"><strong>LMS Portal Link:</strong> <a href="{login_url}" style="color:#852121; text-decoration:none; font-weight:bold;">{login_url}</a></p>
                    <p style="margin:0 0 8px;"><strong>Username:</strong> {student.email or student.username}</p>
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
            f"Welcome to Aryu Academy!\n\n"
            f"LMS Portal Link: {login_url}\n"
            f"Username: {student.email or student.username}\n"
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
    email_msg.send(fail_silently=False)


