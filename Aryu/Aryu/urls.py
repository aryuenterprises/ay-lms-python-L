from django.contrib import admin
import os
from django.urls import path, include, re_path
from django.http import FileResponse, JsonResponse
from django.conf import settings
from aryuapp.social_jwt import SocialLoginCompleteAPIView

def api_root_hidden(request):
    return JsonResponse({'success': False, 'message': 'API root is hidden.'}, status=404)

def serve_logo_plus(request, filename):
    # make this route PUBLIC
    serve_logo_plus.login_required = False

    file_path = os.path.join(settings.MEDIA_ROOT, 'logos', filename)
    if os.path.exists(file_path):
        return FileResponse(open(file_path, 'rb'))

    return JsonResponse({'success': False, 'message': 'Logo not found'}, status=404)

def serve_media(request, path):
    # protect all non-logo media
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Unauthorized access'}, status=403)

    file_path = os.path.join(settings.MEDIA_ROOT, path)

    if not os.path.abspath(file_path).startswith(os.path.abspath(settings.MEDIA_ROOT)):
        return JsonResponse({'success': False, 'message': 'Invalid file path'}, status=400)

    if os.path.exists(file_path):
        return FileResponse(open(file_path, "rb"))

    return JsonResponse({'success': False, 'message': 'File not found'}, status=404)

urlpatterns = [
    path('api/admin/', admin.site.urls),
    path("api/", api_root_hidden),
    path("api/", include("aryuapp.urls")),
    path("accounts/", include("allauth.urls")),
    path("accounts/social-complete/", SocialLoginCompleteAPIView.as_view()),
    path("api/live-quiz/", include("live_quiz.urls")),
    path("api/webinar/", include("webinar.urls")),

    # PUBLIC LOGO URL (FIXED)
    re_path(r'^api/media/logos/(?P<filename>[^/]+)$', serve_logo_plus),

    # PROTECTED MEDIA URL
    re_path(r'^api/media/(?P<path>.*)$', serve_media, name='serve_media'),
]

