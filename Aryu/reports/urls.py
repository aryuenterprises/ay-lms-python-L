from django.urls import path
from reports.views import (
    AryuReportView,
    StudentEnrollmentReportView,
    AttendanceReportView,
    GoogleReviewReportView,
    GoogleReviewDetailView
)

urlpatterns = [
    path('aryu-report/', AryuReportView.as_view()),
    path('reports/attendance', AttendanceReportView.as_view()),
    path('v1/reports/attendance', AttendanceReportView.as_view()),
    path('reports/student-enrollments', StudentEnrollmentReportView.as_view()),
    path('v1/reports/student-enrollments', StudentEnrollmentReportView.as_view()),
    path('reports/google-reviews', GoogleReviewReportView.as_view()),
    path('v1/reports/google-reviews', GoogleReviewReportView.as_view()),
    path('reports/google-reviews/<str:pk>', GoogleReviewDetailView.as_view()),
    path('v1/reports/google-reviews/<str:pk>', GoogleReviewDetailView.as_view())
]