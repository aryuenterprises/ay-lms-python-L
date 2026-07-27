import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Aryu.settings")

django.setup()

from aryuapp.routing import websocket_urlpatterns as aryu_routes
from live_quiz.routing import websocket_urlpatterns as quiz_routes
from webinar.routing import websocket_urlpatterns as webinar_routes
from lead.whatsapp.routing import websocket_urlpatterns as whatsapp_routes
from core.middleware.whatsapp_middleware import JWTAuthMiddleware


application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": JWTAuthMiddleware(
        URLRouter(
            aryu_routes + quiz_routes + webinar_routes + whatsapp_routes
        )
    ),
})
