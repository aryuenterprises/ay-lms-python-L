

from django.urls import path
from .views import *

urlpatterns = [
   path('payment_gateway', PaymentGatewayViewSet.as_view({'get': 'list', 'post': 'create'})),
   path('payment_gateway/<int:pk>', PaymentGatewayViewSet.as_view({'get': 'retrieve', 'patch': 'update', 'put': 'update'})),
   path('payment_transaction', PaymentTransactionViewSet.as_view({'get': 'list', 'post': 'create'})),
   path('payment_transaction/<int:pk>/', PaymentTransactionViewSet.as_view({'get':    'retrieve','put':'update','patch':  'update', 'delete':'destroy',})),
   path('payment_delete/<int:pk>',PaymentTransactionViewSet.as_view({'delete':'delete_student'})),
   path('strip/payment_gateway', StripePaymentViewSet.as_view({'post': 'create_payment'})),
   path('paypal/payment_gateway', PayPalPaymentViewSet.as_view({'post': 'create_payment'})),
   path("razorpay/create", RazorpayPaymentViewSet.as_view({"post": "create"})),
   path("razorpay/verify", RazorpayPaymentViewSet.as_view({"post": "verify_payment"})),
   path('stripe/success/', stripe_success),
   path('stripe/cancel/', stripe_cancel),
]