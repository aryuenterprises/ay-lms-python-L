from django.shortcuts import render
from aryuapp.mixins import LoggingMixin
from .models import *
from .serializers import *
from aryuapp.models import Trainer
from aryuapp.auth import CustomJWTAuthentication
from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated 

# Create your views here.


class AnnouncementViewSet(LoggingMixin, viewsets.ModelViewSet):
    queryset = Announcement.objects.all()
    serializer_class = AnnouncementSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = 'id'
    
    def get_queryset(self):
        user = self.request.user
        qs = Announcement.objects.filter(is_archived=False)

        # -------- SUPER ADMIN --------
        if user.user_type == "super_admin":
            super_admin_id = str(user.user_id)

            admin_ids = Trainer.objects.filter(
                created_by=super_admin_id,
                created_by_type="super_admin",
                is_archived=False
            ).values_list("trainer_id", flat=True)

            allowed_creators = list(admin_ids) + [super_admin_id]

            return qs.filter(created_by__in=allowed_creators).order_by("-created_at")

        # -------- ADMIN --------
        if user.user_type == "admin" and getattr(user, "trainer_id", None):
            admin_trainer_id = str(user.trainer_id)

            super_admin_id = Trainer.objects.filter(
                trainer_id=admin_trainer_id,
                created_by_type="super_admin",
                is_archived=False
            ).values_list("created_by", flat=True).first()

            allowed_creators = [admin_trainer_id]
            if super_admin_id:
                allowed_creators.append(str(super_admin_id))

            return qs.filter(created_by__in=allowed_creators).order_by("-created_at")

        return qs.none()

    def list(self, request, *args, **kwargs):
        user = request.user

        queryset = self.get_queryset()

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {
                "success": True,
                "count": queryset.count(),
                "data": serializer.data
            }
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            first_error = next(iter(serializer.errors.values()))[0]
            return Response({
                "success": False,
                "message": first_error
            }, status=status.HTTP_200_OK)

        announcement = serializer.save()
        return Response({
            "success": True,
            "message": "Announcement created successfully.",
            "data": self.get_serializer(announcement).data
        }, status=status.HTTP_201_CREATED)
        
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data)
        if not serializer.is_valid():
            first_error = next(iter(serializer.errors.values()))[0]
            return Response({
                "success": False,
                "message": first_error
            }, status=status.HTTP_200_OK)

        announcement = serializer.save()
        return Response({
            "success": True,
            "message": "Announcement updated successfully.",
            "data": self.get_serializer(announcement).data
        }, status=status.HTTP_201_CREATED)
        
    def is_archived(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            instance.is_archived = True
            instance.save()
            return Response({ 'success': True ,'message': 'Announcement deleted successfully.'}, status=status.HTTP_200_OK)
        except Announcement.DoesNotExist:
            return Response({ 'success': False,'message': 'Announcement not found.'}, status=status.HTTP_200_OK)
