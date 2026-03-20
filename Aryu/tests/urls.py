

from django.urls import path
from .views import *
from django.conf.urls.static import static

urlpatterns = [
   path('test', TestViewSet.as_view({'get': 'list', 'post': 'create'}), name='test-list'),
   path('test/course/<int:course_id>', TestViewSet.as_view({'get': 'tests_by_course'}), name='tests-by-course'),
   path('test/course/<int:course_id>/<str:student_id>', TestViewSet.as_view({'get': 'test_by_students'}), name='test_by_students'),
   path('test/<int:pk>', TestViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update'}), name='test-detail'),
   path('test/<int:test_id>/student/<str:student_id>/answers', TestViewSet.as_view({'get': 'student_test_answers'}), name='test-student-answers'),
   path('test/<int:test_id>/student/<str:student_id>/result', TestViewSet.as_view({'get': 'student_test_result'}), name='test-student-result'),
   path('test/<int:pk>/questions', TestViewSet.as_view({'get': 'test_questions'}), name='test-questions'),
   path('test/<int:pk>/archive', TestViewSet.as_view({'patch': 'is_archived'}), name='test-archive'),
   path('test/questions', TestQuestionViewSet.as_view({'get': 'list', 'post': 'create'}), name='question-list'),
   path('test/questions/<int:pk>', TestQuestionViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update'}), name='question-detail'),
   path('test/questions/<int:pk>/archive', TestQuestionViewSet.as_view({'patch': 'is_archived'}), name='question-archive'),
   path('answers', StudentAnswerViewSet.as_view({'get': 'list', 'post': 'create'}), name='answer-list'),
   path('answers/<int:pk>', StudentAnswerViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update'}), name='answer-detail'),
   path('results/finalize/<int:test_id>/mark_and_finalize', TestResultViewSet.as_view({'get': 'mark_and_finalize', 'post': 'mark_and_finalize'}), name='result-list'),
   path('results/<int:pk>', TestResultViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update'}), name='result-detail'),
]