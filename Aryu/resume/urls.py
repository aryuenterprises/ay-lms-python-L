from django.urls import path 
from rest_framework_simplejwt.views import (TokenRefreshView)
from .views import *

urlpatterns = [
    #ResumeRegistrations urls
    path('registraion',ResumeRegistrationViewset.as_view({'post':'create','get':'list'})),
    path('registered-user/<int:pk>',ResumeRegistrationViewset.as_view({'patch':'partial_update','delete':'destroy'})),
    path('payments', ResumeTransactionViewSet.as_view({'get':'list'})),

    path("auth/signup/",AuthViewSet.as_view({"post": "signup"}),name="signup"),
    path("auth/login/",AuthViewSet.as_view({"post": "login"}),name="login"),
    path("token/refresh/",CustomTokenRefreshView.as_view(),name="token_refresh"),
    path("auth/verify-email/",AuthViewSet.as_view({"get": "verify_email"}),name="verify_email"),
    path("auth/resend-verification-email/",AuthViewSet.as_view({"post": "resend_verification_email"}),name="resend_verification_email"),
    path("auth/forgot-password/",AuthViewSet.as_view({"post": "forgot_password"}),name="forgot_password"),
    path("auth/verify-reset-otp/",AuthViewSet.as_view({"post": "verify_reset_otp"}),name="verify_reset_otp"),
    path("auth/reset-password/",AuthViewSet.as_view({"post": "reset_password"}),name="reset_password"),

    #dashboard
    path('dashboard', UserDashboardView.as_view(), name='user-dashboard'),

    path('candidates/generate-pdf', GeneratePDFView.as_view(), name='generate_pdf'),

    #templates

    path('templates', ResumeTemplateViewSet.as_view({'get': 'list', 'post': 'create'})),
    path('templates/<int:pk>', ResumeTemplateViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'update_section', 'delete': 'destroy'})),

    # User Resumes Data Lifecycle URLs
    path('user-resumes', UserResumeViewSet.as_view({'post': 'create', 'get': 'list'})),
    path('user-resumes/<int:pk>', UserResumeViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'update_section', 'delete': 'destroy'})),
    
    #payments
    path("payment/create-order/",ResumePaymentViewSet.as_view({"post": "create_order"}),name="resume-create-order"),
    path("payment/verify-payment/",ResumePaymentViewSet.as_view({"post": "verify_payment"}),name="resume-verify-payment"),
    path("payment/webhook/",resume_razorpay_webhook,name="resume-razorpay-webhook"),

    #Contact urls
    path('contact',ContactViewset.as_view({'get':'list','post':'create'})),
    path('contact/<int:pk>',ContactViewset.as_view({'delete':'destroy'})),

    #Subscription Urls
    path("plans/",SubscriptionViewSet.as_view({"get": "plans"}),name="subscription-plans"),
    path("pricing-plans/",PublicSubscriptionPlansViewSet.as_view({"get":"list","post":"create"})),
    path("pricing-plans/<int:pk>",PublicSubscriptionPlansViewSet.as_view({"patch":"update","delete":"destroy"})),
    path("my-subscription/",SubscriptionViewSet.as_view({"get": "my_subscription"}),name="my-subscription"),
    path("subscription-history/",SubscriptionViewSet.as_view({"get": "subscription_history"}),name="subscription-history"),
    path("create-plan/",SubscriptionViewSet.as_view({"post": "create_plan"}),name="create-plan"),
    path("update-plan/<int:plan_id>/",SubscriptionViewSet.as_view({"patch": "update_plan"}),name="update-plan"),
    path("delete-plan/<int:plan_id>/",SubscriptionViewSet.as_view({"patch": "delete_plan"}),name="delete-plan"),

    #PaymentHistoru Urls
    path('paymenthistory',PaymentHistoryViewset.as_view({'get':'list'})),

]