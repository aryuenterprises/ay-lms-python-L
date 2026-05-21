from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.permissions import  AllowAny
from pypdf import PdfReader, PdfWriter
from django.core.files.base import ContentFile
from io import BytesIO
from .models import *
from .serializers import *
# Create your views here.
class ResourcesViewset(viewsets.ModelViewSet):

    queryset = Resources.objects.all().order_by("-id")
    serializer_class = ResourcesSerializers
    permission_classes = [AllowAny]
    authentication_classes = []
    #List
    def list(self, request, *args, **kwargs):

        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        return Response(
            {
                "status": True,
                "message": "Resources list",
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )
  
    # CREATE
    def create(self, request, *args, **kwargs):

        data = request.data.copy()

        uploaded_file = request.FILES.get("file")

        if uploaded_file and uploaded_file.name.endswith(".pdf"):

            reader = PdfReader(uploaded_file)
            writer = PdfWriter()

            for page in reader.pages:
                writer.add_page(page)

            # Set PDF metadata title
            title = data.get("title", "Document")

            writer.add_metadata({
                "/Title": title
            })

            pdf_bytes = BytesIO()
            writer.write(pdf_bytes)
            pdf_bytes.seek(0)

            updated_file = ContentFile(
                pdf_bytes.read(),
                name=uploaded_file.name
            )

            data["file"] = updated_file

        serializer = self.get_serializer(data=data)

        if serializer.is_valid():
            serializer.save()

            return Response(
                {
                    "status": True,
                    "message": "Resources created successfully",
                    "data": serializer.data
                },
                status=status.HTTP_201_CREATED
            )

        return Response(
            {
                "status": False,
                "message": "Validation error",
                "errors": serializer.errors
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    # PATCH / UPDATE
    def partial_update(self, request, *args, **kwargs):

        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():
            serializer.save()

            return Response(
                {
                    "status": True,
                    "message": "Resources updated successfully",
                    "data": serializer.data
                },
                status=status.HTTP_200_OK
            )

        return Response(
            {
                "status": False,
                "message": "Validation error",
                "errors": serializer.errors
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # DELETE
    def destroy(self, request, *args, **kwargs):

        instance = self.get_object()
        instance.delete()

        return Response(
            {
                "status": True,
                "message": "Resource deleted successfully"
            },
            status=status.HTTP_200_OK
        )
   