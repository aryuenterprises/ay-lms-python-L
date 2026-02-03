from django.urls import path
from .views import *
from django.conf.urls.static import static


urlpatterns = [
    # Webinar CRUD
    path('web', WebinarViewSet.as_view({'get': 'list','post': 'create'}), name='webinar-list'),
    path("webhooks/whatsapp/", whatsapp_webhook),
    path('web/<str:uuid>/', WebinarViewSet.as_view({'get': 'retrieve','put': 'update','patch': 'update','delete': 'delete'}), name='webinar-detail'),
    
    # Webinar Registration
    path('<slug:slug>/register/',WebinarRegistrationViewSet.as_view({'post': 'create'}),name='webinar-register'),
    path('<slug:slug>/registrations/',WebinarRegistrationViewSet.as_view({'get': 'list'}),name='webinar-registrations'),

    # Webinar Lifecycle
    path('<str:uuid>/cancel/',WebinarLifecycleViewSet.as_view({'post': 'cancel'}),name='webinar-cancel'),
    path("razorpay/webhook/",razorpay_webhook,name="razorpay-webhook"),
    path("payments/",RazorpayPaymentViewSet.as_view({"post": "create"}),name="payment-create"),
    path("payments/verify/",RazorpayPaymentViewSet.as_view({"post": "verify_payment"}),name="payment-verify"),

    # Public Webinar Views
    path("public/webinars/", PublicWebinarViewSet.as_view({"get": "list"}), name="public-webinar-list"),
    path('public/webinars/<slug:slug>', PublicWebinarViewSet.as_view({"get": "retrieve"}), name='public-webinar-detail'),

    # Webinar Feedback
    path("feedback/",WebinarFeedbackViewSet.as_view({"get": "list","post": "create",}),name="webinar-feedback-list"),
    path("feedback/<uuid:pk>/",WebinarFeedbackViewSet.as_view({"get": "retrieve",}),name="webinar-feedback-detail"),

    # Webinar Session Management
    path('<str:uuid>/session/',WebinarSessionViewSet.as_view({'get': 'retrieve'}),name='webinar-session'),
    path('<uuid>/session/start/', WebinarSessionViewSet.as_view({"post": "start"}), name='webinar-session-start'),
    path('<uuid>/session/end/', WebinarSessionViewSet.as_view({"post": "end"}), name='webinar-session-end'),
    path("<uuid:uuid>/attendance/sync/",WebinarAttendanceViewSet.as_view({'get': 'list',"post": "sync"}),name="webinar-attendance-sync"),
]  + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
