from django.urls import path
from .views import *



urlpatterns = [
    # Webinar CRUD
    path('web', WebinarViewSet.as_view({'get': 'list','post': 'create'}), name='webinar-list'),
    path("webhooks/whatsapp/", whatsapp_webhook),
    path('web/<str:uuid>/', WebinarViewSet.as_view({'get': 'retrieve','put': 'update','patch': 'update','delete': 'delete'}), name='webinar-detail'),

    # Webinar Registration
    path('<str:uuid>/register/',WebinarRegistrationViewSet.as_view({'post': 'create'}),name='webinar-register'),
    path('<str:uuid>/registrations/',WebinarRegistrationViewSet.as_view({'get': 'list'}),name='webinar-registrations'),

    # Webinar Session (Live Status)
    path('<str:uuid>/session/',WebinarSessionViewSet.as_view({'get': 'retrieve'}),name='webinar-session'),
    # Webinar Lifecycle
    path('<str:uuid>/cancel/',WebinarLifecycleViewSet.as_view({'post': 'cancel'}),name='webinar-cancel'),
    path("razorpay/webhook/",razorpay_webhook,name="razorpay-webhook"),
    path(
        "payments/",
        RazorpayPaymentViewSet.as_view({"post": "create"}),
        name="payment-create"
    ),
    path(
        "payments/verify/",
        RazorpayPaymentViewSet.as_view({"post": "verify_payment"}),
        name="payment-verify"
    ),
]

