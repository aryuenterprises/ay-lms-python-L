from django.urls import path
from .views import *
from django.conf.urls.static import static


urlpatterns = [
    # Webinar CRUD
    path('web', WebinarViewSet.as_view({'get': 'list','post': 'create'}), name='webinar-list'),
    path('bootcamp',BootcampViewSet.as_view({'get':'list','post':'create'}),name='webinar-list'),   
    path("webhooks/whatsapp/", whatsapp_webhook),
    path('web/<slug:slug>/', WebinarViewSet.as_view({'get': 'retrieve','put': 'update','patch': 'update','delete': 'destroy'}), name='webinar-detail'),
    path('bootcamp/<slug:slug>/',BootcampViewSet.as_view({'get': 'retrieve','put': 'update','patch': 'update','delete': 'destroy'}), name='webinar-detail'),
    path("<uuid:uuid>/tools/<int:pk>/", WebinarToolUpdateDeleteView.as_view(), name="webinar-tool-update-delete"),
    
    # Webinar Registration
    path('<slug:slug>/register/',WebinarRegistrationViewSet.as_view({'post': 'create'}),name='webinar-register'),
    path('<slug:slug>/registrations/',WebinarRegistrationViewSet.as_view({'get': 'list'}),name='webinar-registrations'),
    path('<slug:slug>/registrations/<int:pk>',WebinarRegistrationViewSet.as_view({'delete':'destroy'}),name='webinar-registrations'),
    path('bootcamp/<slug:slug>/registrations/<int:pk>',BootcampViewSet.as_view({'delete':'destory'}),name='webinar-registrations'),


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
    path("certificates/send/",WebinarCertificateViewSet.as_view({"post": "send"}),name="webinar-certificate-send"),
    path("tickets/", PublicTicketViewSet.as_view({"get": "retrieve", "post": "create"}), name="webinar-ticket-list"),
    path("tickets/<int:pk>/reply/",PublicTicketViewSet.as_view({"post": "reply"}),name="webinar-ticket-reply"),

    # Webinar Session Management
    path('<slug:slug>/session/',WebinarSessionViewSet.as_view({'get': 'retrieve'}),name='webinar-session'),
    path('<slug:slug>/session/start/', WebinarSessionViewSet.as_view({"post": "start"}), name='webinar-session-start'),
    path('<slug>/session/end/', WebinarSessionViewSet.as_view({"post": "end"}), name='webinar-session-end'),
    path("<slug:slug>/attendance/sync/",WebinarAttendanceViewSet.as_view({'get': 'list',"post": "sync"}),name="webinar-attendance-sync"),

    # -------- FORMS --------
    path("forms/", FormViewSet.as_view({"get": "list","post": "create",}), name="form-list-create"),
    path("forms/<slug:slug>/", FormViewSet.as_view({"get": "retrieve", "put": "update", "patch": "update",}), name="form-detail"),
    path("forms/<slug:slug>/delete/",FormViewSet.as_view({"delete": "destroy"}),name="form-delete"),

    # -------- SUBMISSIONS --------
    path("submissions/", SubmissionViewSet.as_view({"get": "list","post": "create",}), name="submission-list-create"),
    path("submissions/<uuid:pk>/", SubmissionViewSet.as_view({"get": "retrieve", "delete": "destroy"}), name="submission-detail"),
    path("public/forms/<slug:slug>/",PublicFormViewSet.as_view({"get": "retrieve"}),name="public-form-detail"),

]  + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
