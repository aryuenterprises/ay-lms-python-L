from django.db.models import Q
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.decorators import action

from aryuapp.mixins import LoggingMixin
from .models import Referral, generate_coupon_code
from .serializers import ReferralSerializer


class ReferralViewSet(LoggingMixin, viewsets.ModelViewSet):
    """
    CRUD ViewSet for Referral module:
    - GET /api/referral/ or /api/referrals/ (List all referrals with optional filters)
    - POST /api/referral/ or /api/referrals/ (Create referral)
    - GET /api/referral/<id>/ or /api/referrals/<id>/ (Retrieve single referral)
    - PUT/PATCH /api/referral/<id>/ or /api/referrals/<id>/ (Update referral)
    - DELETE /api/referral/<id>/ or /api/referrals/<id>/ (Delete referral)
    """
    queryset = Referral.objects.all()
    serializer_class = ReferralSerializer
    permission_classes = [AllowAny]
    lookup_field = "id"

    def get_queryset(self):
        qs = Referral.objects.all().order_by("-created_at")

        status_param = self.request.query_params.get("status")
        if status_param:
            val = status_param.strip().lower()
            if val in ["active", "inactive"]:
                qs = qs.filter(status=val)

        email_param = self.request.query_params.get("email")
        if email_param:
            qs = qs.filter(email__iexact=email_param.strip())

        coupon_param = self.request.query_params.get("coupon_code")
        if coupon_param:
            qs = qs.filter(coupon_code__iexact=coupon_param.strip())

        search_param = self.request.query_params.get("search")
        if search_param:
            search_query = search_param.strip()
            qs = qs.filter(
                Q(name__icontains=search_query)
                | Q(email__icontains=search_query)
                | Q(coupon_code__icontains=search_query)
            )

        return qs

    def get_paginated_response(self, data):
        return Response(
            {
                "success": True,
                "message": "Referrals retrieved successfully.",
                "count": self.paginator.page.paginator.count,
                "next": self.paginator.get_next_link(),
                "previous": self.paginator.get_previous_link(),
                "data": data,
            },
            status=status.HTTP_200_OK,
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {
                "success": True,
                "message": "Referrals retrieved successfully.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(
            {
                "success": True,
                "message": "Referral details retrieved successfully.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "message": "Validation failed.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        obj = self.perform_create(serializer)
        response_serializer = self.get_serializer(obj)
        return Response(
            {
                "success": True,
                "message": "Referral created successfully.",
                "data": response_serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "message": "Validation failed.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        obj = self.perform_update(serializer)
        response_serializer = self.get_serializer(obj)
        return Response(
            {
                "success": True,
                "message": "Referral updated successfully.",
                "data": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(
            {
                "success": True,
                "message": "Referral deleted successfully.",
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get", "post"], url_path="generate")
    def generate(self, request, *args, **kwargs):
        """
        Auto-generates coupon code and url for frontend display without saving directly to the database.
        Accepts optional 'name', 'email', 'password' via POST body or GET query params.
        """
        data = request.data if request.method == "POST" else request.query_params
        name = data.get("name", "")
        email = data.get("email", "")

        if email and Referral.objects.filter(email__iexact=email.strip()).exists():
            return Response(
                {
                    "success": False,
                    "message": "A referral with this email already exists.",
                    "data": None,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        coupon_code = generate_coupon_code()
        url = f"https://passats.aryuacademy.com/{coupon_code}"

        return Response(
            {
                "success": True,
                "message": "Coupon code and URL generated successfully.",
                "data": {
                    "name": name,
                    "email": email,
                    "coupon_code": coupon_code,
                    "url": url,
                },
            },
            status=status.HTTP_200_OK,
        )

