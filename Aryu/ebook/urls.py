from django.urls import path
from .views import *

urlpatterns = [
    path('ebook/', EbookViewSet.as_view({
        'get': 'list',
        'post': 'create'
    })),

    path('ebook/<slug:slug>/', EbookViewSet.as_view({
        'get': 'retrieve',
        'patch': 'update',
        'put': 'update',
        'delete': 'destroy'
    })),   

    #public
    path("public/ebooks/", PublicEbookViewSet.as_view({"get": "list"}), name="public-ebook-list"),
    path('public/ebooks/<slug:slug>', PublicEbookViewSet.as_view({"get": "retrieve"}), name='public-ebook-detail'),
    path("ebooks/details/", EbookPublicListAPIView.as_view({"get":"list"})),

    # Webinar Registration
    path('<slug:slug>/register/',EbookRegistrationViewSet.as_view({'post': 'create'}),name='ebook-register'),
    path(
    "transaction/all/",
    EbookRegistrationViewSet.as_view({"get": "all_transactions"})
    ),
    path(
        "transaction/user-history/",
        EbookRegistrationViewSet.as_view({"get": "user_transaction_history"})
        ),
    path(
        'ebook-registrations/<slug:slug>/',
        EbookRegistrationViewSet.as_view({'get': 'list'})
    ),

    path('reg/<int:pk>/',EbookUserViewSet.as_view({'get':'list','patch':'partial_update'}),name='ebook-reg'),
    path("payments/verify/",RazorpayPaymentViewSet.as_view({"post": "verify_payment"}),name="payment-verify"),
    path("razorpay/webhook/", razorpay_webhook, name="ebook-razorpay-webhook"),
    
    #Reviews
    path('reviews', ReviewListCreateView.as_view(), name='review-list-create'),
    path('reviews/<int:pk>/', ReviewDetailView.as_view(), name='review-detail'),
    path('reviews/<slug:slug>/', EbookReviewBySlugView.as_view(), name='ebook-reviews-by-slug'),
]
