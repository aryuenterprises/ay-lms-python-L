

from django.urls import path
from .views import *
from django.conf.urls.static import static

urlpatterns = [
   path('announcements', AnnouncementViewSet.as_view({'get': 'list', 'post': 'create'})),
   path('announcements/<int:id>', AnnouncementViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update'})),
   path('announcements/<int:id>/archive', AnnouncementViewSet.as_view({'patch': 'is_archived'})),
]