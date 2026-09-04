from rest_framework import (
    status,
    viewsets
)

from rest_framework.response import Response
import logging
from rest_framework.permissions import (
    AllowAny
)
from django.db import transaction
from rest_framework.throttling import AnonRateThrottle
from rest_framework.decorators import action
from .models import *
from .serializers import *
from django.shortcuts import get_object_or_404
from lead.telecrm import sync_lead_to_telecrm
from rest_framework.pagination import PageNumberPagination
logger = logging.getLogger("razorpay_webhook")

class ResourceDownloadRateThrottle(AnonRateThrottle):
    """
    Rates-limits downloads per individual user IP.
    Uses the X-Forwarded-For header set by Nginx (port 8003 proxy).
    """
    rate = "30/minute"

    def get_ident(self, request):
        # 1. Read X-Forwarded-For header set by your Nginx location /api/ block
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        
        if x_forwarded_for:
            # Format from Nginx: "client_ip, proxy_ip"
            # The first IP is always the end user's real public IP
            return x_forwarded_for.split(",")[0].strip()

        # 2. Fallback to X-Real-IP
        x_real_ip = request.META.get("HTTP_X_REAL_IP")
        if x_real_ip:
            return x_real_ip.strip()

        # 3. Direct connection fallback (e.g. local dev without Nginx)
        return request.META.get("REMOTE_ADDR")

class CustomPageNumberPagination(PageNumberPagination):
    page_size = 25                      # Default items per page
    page_size_query_param = "page_size" # Allows the client to override page size using ?page_size=50
    max_page_size = 100

class ResourcesViewSet(viewsets.ModelViewSet):
    queryset = Resources.objects.all().order_by("-id")
    serializer_class = ResourcesSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    pagination_class = CustomPageNumberPagination

    def get_object(self):
        """
        Custom lookup to support fetching/updating records by either integer ID (pk) or string slug.
        """
        queryset = self.filter_queryset(self.get_queryset())
        
        # Extract lookup value from URL kwargs ('pk', 'id', or 'slug')
        lookup_value = (
            self.kwargs.get("pk") 
            or self.kwargs.get("id") 
            or self.kwargs.get("slug")
        )

        filter_kwargs = {}
        if str(lookup_value).isdigit():
            filter_kwargs["pk"] = lookup_value
        else:
            filter_kwargs["slug"] = lookup_value

        obj = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj

    def get_throttles(self):
        if self.action == "download":
            return [ResourceDownloadRateThrottle()]
        return super().get_throttles()

    def get_serializer_context(self):
        return {"request": self.request}

    def retrieve(self, request, *args, **kwargs):
        resource = self.get_object()
        serializer = self.get_serializer(resource)
        return Response(
            {
                "success": True,
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["post"], url_path="download")
    def download(self, request, *args, **kwargs):
        try:
            resource = self.get_object()

            # 1. Process Lead Form if enabled on resource
            if resource.form:
                lead_serializer = LeadCaptureSerializer(data=request.data)

                # Validation failure
                if not lead_serializer.is_valid():
                    return Response(
                        {
                            "success": False,
                            "message": "Validation failed",
                            "errors": lead_serializer.errors,
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                validated_data = lead_serializer.validated_data
                phone = validated_data.get("phone")

                lead_defaults = {
                    "name": validated_data.get("name") or None,
                    "email": validated_data.get("email") or None,
                    "city": validated_data.get("city") or None,
                    "qualification": validated_data.get("qualification") or None,
                    "course_interested_in": validated_data.get("course_interested_in") or None,
                    "interested": validated_data.get("interested", True),
                    "source": validated_data.get("source") or "Resource Download",
                    "source_campaign": f"{resource.slug}",
                    "status": "fresh",
                }

                # Atomic execution handling duplicate phone entries safely
                with transaction.atomic():
                    existing_lead = Lead.objects.filter(phone=phone).order_by("-id").first()

                    if existing_lead:
                        for key, value in lead_defaults.items():
                            if value is not None:
                                setattr(existing_lead, key, value)

                        download_note = f"Downloaded: {resource.title}"
                        if existing_lead.message:
                            if download_note not in existing_lead.message:
                                existing_lead.message = f"{existing_lead.message} | {download_note}"
                        else:
                            existing_lead.message = download_note

                        existing_lead.save()
                        target_lead = existing_lead
                    else:
                        target_lead = Lead.objects.create(
                            phone=phone,
                            message=f"Downloaded: {resource.title}",
                            **lead_defaults,
                        )

                    # ==========================================
                    # TELECRM RESOURCE DOWNLOAD SYNC
                    # ==========================================
                    sync_lead_to_telecrm(
                        target_lead,
                        action_type="ACTION_1001",
                        action_note=f"Resource Downloaded: {resource.title}",
                        extra_fields={
                            "source": lead_defaults.get("source"),
                            "source_campaign": lead_defaults.get("source_campaign"),
                            "course_interested_in": lead_defaults.get("course_interested_in"),
                        }
                    )

            # 2. Return Response
            resource_serializer = self.get_serializer(resource)
            return Response(
                {
                    "success": True,
                    "message": f"Downloaded: {resource.title}",
                    "download_url": resource_serializer.data.get("file_url"),
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(f"Error processing resource download: {str(e)}", exc_info=True)
            return Response(
                {
                    "success": False,
                    "message": f"An unexpected server error occurred: {str(e)}",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
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

            download_url = request.build_absolute_uri(resource.file.url)
            if "/media/" in download_url and "/api/media/" not in download_url:
                download_url = download_url.replace("/media/", "/api/media/")

            return Response(
                {
                    "status": True,

                    "message":
                        "Form submitted successfully",

                    "download_url":
                        download_url,

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