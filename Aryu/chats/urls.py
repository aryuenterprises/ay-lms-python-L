

from django.urls import path
from .views import *
from django.conf.urls.static import static

urlpatterns = [
   path("notifications", NotificationListView.as_view(), name="notification-list"),
   path("notifications/mark_read", mark_notification_read, name="notification-mark-read"),
   path('admins/chat-logs', AdminChatLogViewSet.as_view({'get': 'admin_chat_logs'}), name='admin-chat-logs'),
   path('chat/allama', ChatRoomViewSet.as_view({'get': 'list', 'post': 'create'}), name='chat-list'),
   path('chat/bibbwdx/<int:pk>', ChatRoomViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update'}), name='chat-room-detail'),
   path('chat/rooms/<int:room_id>/euybfvh',MessageViewSet.as_view({'get': 'list', 'post': 'create'}), name='message-list'),
   path('chat/yfhyjyft/<int:pk>', MessageViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update'}), name='message-detail'),
   path('chat/gcjkhby/<int:room_id>/ywvdajhb', MessageViewSet.as_view({'post': 'mark_as_read'}), name='message-mark-read'),
   path('chat/rooms/<int:room_id>/uyfvchky', MessageViewSet.as_view({'get': 'unread_messages'}), name='unread-count'),
   path('chating/<str:student_id>/eduthuko', ChatRoomViewSet.as_view({'get': 'student_chat_logs'}), name='chating-by-student'),
]