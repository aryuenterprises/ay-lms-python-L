from django.urls import path 
from .views import *

urlpatterns = [
    #Resources urls
    path('resources',ResourcesViewset.as_view({'post':'create','get':'list'})),
    path('resources/<int:pk>',ResourcesViewset.as_view({'patch':'partial_update','delete':'destroy'})),
]