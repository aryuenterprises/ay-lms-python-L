
from django.urls import path
from .views import *
from django.conf.urls.static import static

urlpatterns = [
    path('feedback', FeedbackViewSet.as_view({'get': 'list', 'post': 'create'})),
]

