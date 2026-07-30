from rest_framework import (
    status,
    viewsets
)

from rest_framework.response import Response

from rest_framework.permissions import (
    AllowAny
)
from django.db import transaction
from rest_framework.throttling import AnonRateThrottle
from rest_framework.decorators import action
from .models import *
from .serializers import *
from django.shortcuts import get_object_or_404

class ResourceDownloadRateThrottle(AnonRateThrottle):
    """
    Prevents API abuse and automated bots from spamming downloads.
    Allows up to 30 submissions per minute per IP.
    """
    rate = "30/minute"


class ResourcesViewSet(viewsets.ModelViewSet):
    queryset = Resources.objects.all().order_by("-id")
    serializer_class = ResourcesSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    lookup_field = "slug"

    def get_throttles(self):
        if self.action == "download":
            return [ResourceDownloadRateThrottle()]
        return super().get_throttles()

    def get_serializer_context(self):
        return {"request": self.request}

    def retrieve(self, request, slug=None):
        resource = get_object_or_404(Resources, slug=slug)
        serializer = self.get_serializer(resource)
        return Response(
            {
                "success": True,
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["post"], url_path="download")
    def download(self, request, slug=None):
        """
        POST /api/resources/<slug>/download/
        Handles synchronous lead capture and provides download URL.
        """
        resource = get_object_or_404(Resources, slug=slug)

        # 1. If resource requires user information (form = True)
        if resource.form:
            lead_serializer = LeadCaptureSerializer(data=request.data)
            if not lead_serializer.is_valid():
                return Response(
                    {
                        "success": False,
                        "errors": lead_serializer.errors
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            data = lead_serializer.validated_data
            phone = data.pop("phone")

            # Synchronously create/update lead in an atomic transaction to avoid race conditions
            with transaction.atomic():
                Lead.objects.update_or_create(
                    phone=phone,
                    defaults={
                        "name": data.get("name"),
                        "email": data.get("email"),
                        "city": data.get("city"),
                        "qualification": data.get("qualification"),
                        "course_interested_in": data.get("course_interested_in"),
                        "interested": data.get("interested", True),
                        "source": data.get("source", "Resource Download"),
                        "source_campaign": f"Downloaded: {resource.title}",
                        "status": "fresh",
                    },
                )

        # 2. Return file URL dynamically back to user
        resource_serializer = self.get_serializer(resource)

        return Response(
            {
                "success": True,
                "message": "Information captured successfully" if resource.form else "Download ready",
                "download_url": resource_serializer.data.get("file_url"),
            },
            status=status.HTTP_200_OK,
        )


# =====================================================
# FORM VIEWSET
# =====================================================

class FormViewset(
    viewsets.ViewSet
):

    permission_classes = [AllowAny]

    authentication_classes = []

    # ==========================================
    # CREATE
    # ==========================================

    def create(self, request):

        

        resource_id = request.data.get(
            "resource_id"
        )

        if not resource_id:

            return Response(
                {
                    "status": False,
                    "message":
                        "resource_id is required"
                },
                status=400
            )

        resource = (
            Resources.objects
            .filter(id=resource_id)
            .first()
        )

        if not resource:

            return Response(
                {
                    "status": False,
                    "message":
                        "Resource not found"
                },
                status=404
            )

        data = request.data.copy()

        data["resource"] = (
            resource.id
        )

        serializer = FormSerializer(
            data=data
        )

        if serializer.is_valid():

            form = serializer.save()

            return Response(
                {
                    "status": True,

                    "message":
                        "Form submitted successfully",

                    "download_url":
                        request.build_absolute_uri(
                            resource.file.url
                        ),

                    "data":
                        FormSerializer(form).data
                },
                status=201
            )

        return Response(
            {
                "status": False,
                "errors":
                    serializer.errors
            },
            status=400
        )

    # ==========================================
    # LIST
    # ==========================================

    def list(self, request):

        queryset = (
            Form.objects.all()
            .order_by("-id")
        )

        serializer = FormSerializer(
            queryset,
            many=True
        )

        return Response(
            {
                "status": True,
                "data": serializer.data
            }
        )

    # ==========================================
    # RETRIEVE
    # ==========================================

    def retrieve(self, request, pk=None):

        form = Form.objects.filter(
            id=pk
        ).first()

        if not form:

            return Response(
                {
                    "status": False,
                    "message":
                        "Form not found"
                },
                status=404
            )

        serializer = FormSerializer(
            form
        )

        return Response(
            {
                "status": True,
                "data": serializer.data
            }
        )

    # ==========================================
    # DELETE
    # ==========================================

    def destroy(self, request, pk=None):

        form = Form.objects.filter(
            id=pk
        ).first()

        if not form:

            return Response(
                {
                    "status": False,
                    "message":
                        "Form not found"
                },
                status=404
            )

        form.delete()

        return Response(
            {
                "status": True,
                "message":
                    "Form deleted successfully"
            }
        )