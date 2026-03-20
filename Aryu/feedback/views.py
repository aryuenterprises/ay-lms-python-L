from .models import Feedback
from .serializers import FeedbackSerializer
from aryuapp.mixins import LoggingMixin
from rest_framework import viewsets

# Create your views here.


class FeedbackViewSet(LoggingMixin, viewsets.ModelViewSet):
    queryset = Feedback.objects.all()
    serializer_class = FeedbackSerializer

    