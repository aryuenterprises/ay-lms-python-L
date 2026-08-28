from django.urls import path
from .views import BonusViewSet
from webinar.views import WebinarViewSet

urlpatterns = [
    path(
        'bonus/',
        BonusViewSet.as_view({
            'get': 'list',
            'post': 'create'
        })
    ),
    path(
        'bonus/<int:pk>/',
        BonusViewSet.as_view({
            'put': 'update',
            'patch': 'update',
            'delete': 'destroy'
        })
    ),
    path(
        "webinar/<slug:slug>/bonus-students/",
        WebinarViewSet.as_view({"get": "bonus_students"})
    ),

    path(
        "bonus/send-manual-bonus/",
        BonusViewSet.as_view({"post": "send_manual_bonus"})
    ),

]