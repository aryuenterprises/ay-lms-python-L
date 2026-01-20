from django.urls import re_path
from .consumers import WebinarConsumer

websocket_urlpatterns = [
    re_path(
        r'ws/webinar/(?P<webinar_id>[0-9a-f-]+)/$',
        WebinarConsumer.as_asgi()
    ),
]
