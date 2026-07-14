
from django.urls import path
from .views import *

urlpatterns = [
   path('batches/trainer/<str:trainer_id>', NewBatchViewSet.as_view({'get': 'trainer_batches'})),
   path('batches/student/<str:student_id>', NewBatchViewSet.as_view({'get': 'student_batches'})),
   path('class_schedule', ClassScheduleView.as_view({'get': 'list', 'post': 'create'})),
   path('class_schedule/<str:schedule_id>', ClassScheduleView.as_view({'get': 'retrieve', 'patch': 'update','put':'update'})),
   path('class_schedule/<str:employee_id>/schedules', ClassScheduleView.as_view({'get': 'schedules'})),
   path('class_schedule/<str:schedule_id>/archive', ClassScheduleView.as_view({'patch': 'archive'})),
   path("recurring_schedules", RecurringScheduleView.as_view({"post": "create", "get": "list"}),name="recurring_schedules"),
   path("recurring_schedules/<str:pk>", RecurringScheduleView.as_view({"get": "retrieve", "put": "update", "patch": "partial_update"}),name="recurring_schedule-detail"),
   path('batch', BatchViewSet.as_view({'get': 'list', 'post': 'create'})),
   path('batch/<str:batch_id>', BatchViewSet.as_view({'get': 'list', 'put': 'update', 'patch': 'partial_update'})),
   path('batch/<str:batch_id>/archive', BatchViewSet.as_view({'patch': 'is_archived'})),
   path('batches', NewBatchViewSet.as_view({'get': 'list', 'post': 'create'})),
   path('batches/<str:batch_id>', NewBatchViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'update'})),
   path('batches/<str:batch_id>/archive', NewBatchViewSet.as_view({'patch': 'is_archived'})),
   path('batch-recordings/',BatchRecordingViewSet.as_view({'post':'create','get':'list'})),
   path('batch-recordings/<int:pk>/',BatchRecordingViewSet.as_view({'get': 'retrieve','put': 'update','patch': 'partial_update','delete': 'destroy',})),
]