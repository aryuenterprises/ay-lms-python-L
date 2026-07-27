from django.urls import re_path
from .consumers import SmartInboxConsumer

websocket_urlpatterns = [
    # Captures your real-time live chat streams based on queue query parameters
    # URL format: ws://<domain>/ws/whatsapp/live-chat/?queue=active
    re_path(r"^ws/whatsapp/live-chat/$", SmartInboxConsumer.as_asgi()),
]