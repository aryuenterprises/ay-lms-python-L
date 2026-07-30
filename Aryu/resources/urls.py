from django.urls import path 
from .views import *

urlpatterns = [
    #Resources urls
    path('resources',ResourcesViewSet.as_view({'post':'create','get':'list'})),
    path('resources/<int:pk>',ResourcesViewSet.as_view({'patch':'partial_update','delete':'destroy'})),
    path("resources/<slug:slug>/",ResourcesViewSet.as_view({"get": "retrieve"}),name="retrieve",),
    #FormsUrls
    path('form',FormViewset.as_view({'post':'create','get':'list','delete':'destroy'})),

    #downaload
    path("resources/<slug:slug>/download/",ResourcesViewSet.as_view({"post": "download"}),name="download",),

]