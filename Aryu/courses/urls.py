from django.urls import path
from .views import *

urlpatterns = [
   path('courses', CourseViewSet.as_view({'get': 'list', 'post': 'create', 'put': 'update', 'patch': 'partial_update'})),
   path('courses/<str:course_id>', CourseViewSet.as_view({'get': 'retrieve','put': 'update','patch': 'partial_update','delete': 'destroy'})),
   path('courses/<str:course_id>/batches', CourseViewSet.as_view({'get': 'get_batches'})),
   path('courses/<str:course_id>/archive', CourseViewSet.as_view({'patch': 'archive_course'})),
   path('course_categories', CourseCategoryViewSet.as_view({'get': 'list', 'post': 'create'})),
   path('course_categories/<str:category_id>', CourseCategoryViewSet.as_view({'get': 'retrieve','put': 'update','patch': 'partial_update',})),
   path('course_categories/<str:category_id>/archive', CourseCategoryViewSet.as_view({'patch': 'archive_category'})),
   path('courses/<str:course_id>/topic', TopicViewSet.as_view({'get': 'list','post': 'create'}), name='topic-list'),
   path('courses/<str:course_id>/topic/<str:student_id>/status', StudentTopicStatusViewSet.as_view({ 'get': 'list' ,'post': 'create'}), name='topic-status'),
   path('courses/<str:course_id>/topic/<int:pk>', TopicViewSet.as_view({'get': 'retrieve','put': 'update','patch': 'partial_update',}), name='topic-detail'),
   path('courses/<str:course_id>/topic/<int:pk>/archive', TopicViewSet.as_view({'patch': 'destroy'})),
]

   