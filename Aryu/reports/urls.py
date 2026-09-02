from django.urls import path
from reports.views import AryuReportView, StudentEnrollmentReportView

urlpatterns = [
    path('aryu-report/', AryuReportView.as_view()),
    path('reports/student-enrollments', StudentEnrollmentReportView.as_view())
]