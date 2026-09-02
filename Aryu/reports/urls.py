from django.urls import path
from reports.views import AryuReportView, StudentEnrollmentReportView, AttendanceReportView

urlpatterns = [
    path('aryu-report/', AryuReportView.as_view()),
    path('v1/reports/attendance', AttendanceReportView.as_view()),
    path('reports/attendance', AttendanceReportView.as_view()),
    path('attendance', AttendanceReportView.as_view()),
    path('reports/student-enrollments', StudentEnrollmentReportView.as_view()),
    path('student-enrollments', StudentEnrollmentReportView.as_view())
]