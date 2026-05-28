from rest_framework import (
    status,
    viewsets
)

from rest_framework.response import Response

from rest_framework.permissions import (
    AllowAny
)

from .models import *
from .serializers import *


# =====================================================
# RESOURCE VIEWSET
# =====================================================

class ResourcesViewset(viewsets.ModelViewSet):

    queryset = (Resources.objects.all().order_by("-id"))
    serializer_class = (ResourcesSerializers)
    permission_classes = [AllowAny]
    authentication_classes = []
    def get_serializer_context(self):

        return {
            "request": self.request
        }


# =====================================================
# FORM VIEWSET
# =====================================================

# class FormViewset(
#     viewsets.ViewSet
# ):

#     permission_classes = [AllowAny]

#     authentication_classes = []

#     # ==========================================
#     # CREATE
#     # ==========================================

#     def create(self, request):

        

#         resource_id = request.data.get(
#             "resource_id"
#         )

#         if not resource_id:

#             return Response(
#                 {
#                     "status": False,
#                     "message":
#                         "resource_id is required"
#                 },
#                 status=400
#             )

#         resource = (
#             Resources.objects
#             .filter(id=resource_id)
#             .first()
#         )

#         if not resource:

#             return Response(
#                 {
#                     "status": False,
#                     "message":
#                         "Resource not found"
#                 },
#                 status=404
#             )

#         data = request.data.copy()

#         data["resource"] = (
#             resource.id
#         )

#         serializer = FormSerializer(
#             data=data
#         )

#         if serializer.is_valid():

#             form = serializer.save()

#             return Response(
#                 {
#                     "status": True,

#                     "message":
#                         "Form submitted successfully",

#                     "download_url":
#                         request.build_absolute_uri(
#                             resource.file.url
#                         ),

#                     "data":
#                         FormSerializer(form).data
#                 },
#                 status=201
#             )

#         return Response(
#             {
#                 "status": False,
#                 "errors":
#                     serializer.errors
#             },
#             status=400
#         )

#     # ==========================================
#     # LIST
#     # ==========================================

#     def list(self, request):

#         queryset = (
#             Form.objects.all()
#             .order_by("-id")
#         )

#         serializer = FormSerializer(
#             queryset,
#             many=True
#         )

#         return Response(
#             {
#                 "status": True,
#                 "data": serializer.data
#             }
#         )

#     # ==========================================
#     # RETRIEVE
#     # ==========================================

#     def retrieve(self, request, pk=None):

#         form = Form.objects.filter(
#             id=pk
#         ).first()

#         if not form:

#             return Response(
#                 {
#                     "status": False,
#                     "message":
#                         "Form not found"
#                 },
#                 status=404
#             )

#         serializer = FormSerializer(
#             form
#         )

#         return Response(
#             {
#                 "status": True,
#                 "data": serializer.data
#             }
#         )

#     # ==========================================
#     # DELETE
#     # ==========================================

#     def destroy(self, request, pk=None):

#         form = Form.objects.filter(
#             id=pk
#         ).first()

#         if not form:

#             return Response(
#                 {
#                     "status": False,
#                     "message":
#                         "Form not found"
#                 },
#                 status=404
#             )

#         form.delete()

#         return Response(
#             {
#                 "status": True,
#                 "message":
#                     "Form deleted successfully"
#             }
#         )
    