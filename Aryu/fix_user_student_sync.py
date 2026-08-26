import os
import sys
import django

# Setup django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Aryu.settings")
django.setup()

from django.contrib.auth import get_user_model
from django.db import transaction
from aryuapp.models import Student, Role
from django.contrib.auth.hashers import make_password, check_password

def main():
    User = get_user_model()
    test_email = "tamilselvi12022004@gmail.com"
    raw_password = "AryuPassword@2026"

    with transaction.atomic():
        # Get or create Student role
        role = Role.objects.filter(name__iexact="student").first()
        if not role:
            role = Role.objects.create(name="student")
            print(f"[+] Created role: student")

        # 1. Get or Create the Auth User
        user = User.objects.filter(email__iexact=test_email).first() or User.objects.filter(username__iexact=test_email).first()
        if not user:
            user = User.objects.create_user(
                username=test_email,
                email=test_email,
                password=raw_password,
                full_name="Tamil Selvi",
                is_active=True
            )
            print(f"[+] Created auth user: {user.username}")
        else:
            user.username = test_email
            user.email = test_email
            user.set_password(raw_password)
            user.is_active = True
            print(f"[+] Synced auth user password: {user.username}")

        # Set user role and type
        user.user_type = "student"
        user.role = role
        user.save()
        print(f"[+] Configured user role to: {getattr(user.role, 'name', None)} and user_type to: {user.user_type}")

        # 2. Sync Student Record
        student = Student.objects.filter(email__iexact=test_email).first()
        if not student:
            student = Student.objects.create(
                first_name="Tamil Selvi",
                username=test_email,
                email=test_email,
                password=make_password(raw_password),
                contact_no="9876543210",
                current_address="Chennai, Tamil Nadu",
                permanent_address="Chennai, Tamil Nadu",
                city="Chennai",
                state="Tamil Nadu",
                country="India",
                converter="system",
                role=role,
                status=True,
                is_archived=False
            )
            print(f"[+] Created student record: {student.email}")
        else:
            student.password = make_password(raw_password)
            student.status = True
            student.is_archived = False
            student.role = role
            student.username = test_email
            student.save()
            print(f"[+] Synced student record credentials & active status: {student.email}")

        print(f"[+] Synced User ID: {user.id}, Student ID: {student.student_id}")

    # 3. Simulate Login Viewset Authentication Payload
    print("\n--- SIMULATING LOGIN RESPONSE ---")
    from rest_framework_simplejwt.tokens import RefreshToken

    # Validate auth matches Login class logic
    user_authenticated = False
    matched_user = User.objects.filter(username=test_email, is_active=True).first()
    if matched_user and check_password(raw_password, matched_user.password):
        user_authenticated = True
        user_type = getattr(matched_user, "user_type", "admin")
        print(f"Login Status : SUCCESS")
        print(f"Username     : {matched_user.username}")
        print(f"Login Type   : {user_type} (Expected: 'student')")
        
        refresh = RefreshToken.for_user(matched_user)
        print(f"Access Token : {str(refresh.access_token)[:25]}...")
    else:
        print("Login Status : FAILED")

if __name__ == "__main__":
    main()
