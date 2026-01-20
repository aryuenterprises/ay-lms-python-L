from rest_framework.views import APIView
from rest_framework.response import Response
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
import jwt

from aryuapp.models import Student, Settings, Lead

class SocialLoginCompleteAPIView(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        temp_user = request.user

        if not temp_user or not temp_user.is_authenticated:
            return Response(
                {"success": False, "message": "Not authenticated via social"},
                status=401
            )

        email = getattr(temp_user, "email", None)
        name = getattr(temp_user, "first_name", "") or ""
        
        if not email:
            return Response(
                {"success": False, "message": "Email not returned by provider"},
                status=400,
            )

        student = Student.objects.filter(email=email).first()

        if student:
            # Lead -> Student conversion handled here:
            # If the user was a lead earlier, they now login as student.
            
            system_settings = Settings.objects.first()

            payload = {
                "registration_id": student.registration_id,
                "student_id": student.student_id,
                "username": student.username,
                "user_type": "student",
                "attendance_type": system_settings.attendance_options if system_settings else None,
                "student_type": student.student_type,
                "exp": int((timezone.now() + timedelta(minutes=30)).timestamp()),
            }

            token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

            return Response({
                "success": True,
                "loginType": "student",
                "message": "Login successful",
                "token": token,
                "user": {
                    "registration_id": student.registration_id,
                    "student_id": student.student_id,
                    "username": student.username,
                    "user_type": "student",
                    "attendance_type": system_settings.attendance_options if system_settings else None,
                    "student_type": student.student_type,
                },
            })

        lead = Lead.objects.filter(email=email).first()

        if lead:
            return Response({
                "success": True,
                "loginType": "lead",
                "message": "Existing lead login",
                "lead": {
                    "lead_id": lead.id,
                    "name": lead.name,
                    "email": lead.email,
                    "phone": lead.phone,
                    "status": lead.status,
                    "source": lead.source,
                }
            })


        lead = Lead.objects.create(
            name=name,
            email=email,
            interested=True,
            status="new",
            source="social_login"
        )

        return Response({
            "success": True,
            "loginType": "lead",
            "message": "New lead created",
            "lead": {
                "lead_id": lead.id,
                "name": lead.name,
                "email": lead.email,
                "phone": lead.phone,
                "status": lead.status,
                "source": lead.source,
            }
        })
