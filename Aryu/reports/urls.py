from django.urls import path
from reports.views import AryuReportView

urlpatterns = [
    path('aryu-report/', AryuReportView.as_view()),
]