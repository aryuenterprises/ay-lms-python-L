from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db import transaction

from .models import Bonus, BonusFile
from .serializers import BonusSerializer
from webinar.models import Webinar
from webinar_bonus.email import send_bonus_email
from webinar.models import WebinarRegistration


class BonusViewSet(viewsets.ModelViewSet):
    queryset = Bonus.objects.select_related("webinar").all().order_by("-id")
    serializer_class = BonusSerializer

    
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        serializer = self.get_serializer(
            queryset,
            many=True,
            context={"request": request}
        )

        return Response({
            "success": True,
            "count": queryset.count(),
            "data": serializer.data
        })

    
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        webinar_id = request.data.get("webinar") or request.data.get("webinar_id")
        description = request.data.get("description")
        files = request.FILES.getlist("files")

        if not webinar_id or str(webinar_id).strip() in ["undefined", "null", "NaN", ""]:
            return Response(
                {"success": False, "message": "Webinar is required"},
                status=400
            )

        try:
            webinar = Webinar.objects.get(id=int(webinar_id))
        except (Webinar.DoesNotExist, ValueError, TypeError):
            return Response(
                {"success": False, "message": "Invalid webinar"},
                status=400
            )

        bonus = Bonus.objects.create(
            webinar=webinar,
            description=description
        )

        for f in files:
            BonusFile.objects.create(bonus=bonus, file=f)

        serializer = self.get_serializer(
            bonus,
            context={"request": request}
        )

        return Response({
            "success": True,
            "data": serializer.data
        }, status=status.HTTP_201_CREATED)


    def update(self, request, *args, **kwargs):
        instance = self.get_object()

        # update fields
        description = request.data.get("description")
        if description is not None and description not in ["undefined", "null", "NaN"]:
            instance.description = description

        webinar_id = request.data.get("webinar") or request.data.get("webinar_id")
        if webinar_id and str(webinar_id).strip().isdigit():
            instance.webinar_id = int(webinar_id)

        instance.save()

        # update files
        files = request.FILES.getlist("files")

        if files:
            # delete old files
            instance.files.all().delete()

            for f in files:
                BonusFile.objects.create(bonus=instance, file=f)

        serializer = self.get_serializer(
            instance,
            context={"request": request}
        )

        return Response({
            "success": True,
            "data": serializer.data
        })

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)
    
    def destroy(self, request, pk=None):
        instance = self.get_object()
        instance.delete()

        return Response({
            "success": True,
            "message": "Bonus deleted successfully"
        })

   
    @action(detail=False, methods=["get"], url_path="webinar-dropdown")
    def webinar_dropdown(self, request):
        data = Webinar.objects.filter(
            is_deleted=False,
            webinar_status=True
        ).values("id", "title").order_by("-id")

        return Response({
            "success": True,
            "data": list(data)
        })
    
    @action(detail=True, methods=["get"], url_path="bonus-students")
    def bonus_students(self, request, pk=None):
        webinar = self.get_object()

        registrations = WebinarRegistration.objects.filter(webinar=webinar)

        data = []

        for reg in registrations:
            summary = getattr(reg, "attendance_summary", None)
            duration = summary.total_duration_seconds if summary else 0

            data.append({
                "id": reg.id,
                "name": reg.name,
                "email": reg.email,
                "duration_minutes": duration // 60,
                "eligible": duration >= 5400
            })

        return Response({"data": data})
    @action(detail=False, methods=["post"], url_path="send-manual-bonus")
    def send_manual_bonus(self, request):
        reg_id = request.data.get("registration_id")

        reg = WebinarRegistration.objects.get(id=reg_id)
        webinar = reg.webinar

        bonus_files = BonusFile.objects.filter(bonus__webinar=webinar)

        send_bonus_email(reg, webinar, bonus_files)

        return Response({"success": True, "message": "Email sent"})