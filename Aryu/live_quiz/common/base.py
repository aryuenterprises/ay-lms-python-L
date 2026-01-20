from rest_framework import viewsets, status
from rest_framework.response import Response


class BaseViewSet(viewsets.ViewSet):

    def success(self, message="Success", data=None, status_code=status.HTTP_200_OK):
        payload = {
            "success": True,
            "message": message
        }
        if data is not None:
            payload["data"] = data
        return Response(payload, status=status_code)

    def error(self, message="Something went wrong", status_code=status.HTTP_400_BAD_REQUEST):
        return Response({
            "success": False,
            "message": message
        }, status=status_code)
