from .models import *
from .serializers import *
from rest_framework.exceptions import ValidationError, NotFound
from aryuapp.auth import CustomJWTAuthentication
from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action, api_view
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser
from django.contrib.auth.hashers import *
from django.db.models import Q
from aryuapp.mixins import LoggingMixin,NotesMixin
from aryuapp.models import ModulePermission, Student, Trainer
from aryuapp.views import has_permission,flatten_errors
from django.shortcuts import get_object_or_404
import traceback
from batches.serializers import NewBatchSerializer
from django.db import transaction
# Create your views here.





CURRENCIES = [
    {"code": "USD", "name": "United States Dollar", "symbol": "$"},
    {"code": "EUR", "name": "Euro", "symbol": "€"},
    {"code": "GBP", "name": "British Pound Sterling", "symbol": "£"},
    {"code": "INR", "name": "Indian Rupee", "symbol": "₹"},
    {"code": "JPY", "name": "Japanese Yen", "symbol": "¥"},
    {"code": "AUD", "name": "Australian Dollar", "symbol": "A$"},
    {"code": "CAD", "name": "Canadian Dollar", "symbol": "C$"},
    {"code": "CHF", "name": "Swiss Franc", "symbol": "CHF"},
    {"code": "CNY", "name": "Chinese Yuan", "symbol": "¥"},
    {"code": "SAR", "name": "Saudi Riyal", "symbol": "﷼"},
    {"code": "AED", "name": "UAE Dirham", "symbol": "د.إ"},
    {"code": "SGD", "name": "Singapore Dollar", "symbol": "S$"},
    {"code": "ZAR", "name": "South African Rand", "symbol": "R"},
    {"code": "BRL", "name": "Brazilian Real", "symbol": "R$"},
    {"code": "RUB", "name": "Russian Ruble", "symbol": "₽"},
    {"code": "KRW", "name": "South Korean Won", "symbol": "₩"},
    {"code": "MXN", "name": "Mexican Peso", "symbol": "$"},
    {"code": "SEK", "name": "Swedish Krona", "symbol": "kr"},
    {"code": "NZD", "name": "New Zealand Dollar", "symbol": "NZ$"},
    {"code": "THB", "name": "Thai Baht", "symbol": "฿"},
]

@api_view(['GET'])
def currency_list(request):
    return Response({"currencies": CURRENCIES})

class CourseCategoryViewSet(LoggingMixin, viewsets.ModelViewSet):
    queryset = CourseCategory.objects.all()
    serializer_class = CourseCategorySerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = 'category_id' 

    def get_queryset(self):
        user = self.request.user
        base_queryset = CourseCategory.objects.filter(is_archived=False)

        user_created_id = None
        if user.user_type == "super_admin":
            user_created_id = getattr(user, "user_id", None)
        elif user.user_type == "admin":
            user_created_id = getattr(user, "trainer_id", None)

        admin_ids = []
        if user.user_type == "super_admin" and user_created_id:
            admin_ids = Trainer.objects.filter(
                created_by=user_created_id,
                created_by_type="super_admin",
                is_archived=False
            ).values_list("trainer_id", flat=True)

            admin_ids = [str(i) for i in admin_ids]

        if user.user_type == "super_admin" and user_created_id:
            base_queryset = base_queryset.filter(
                Q(created_by_type="super_admin", created_by=str(user_created_id)) |
                Q(created_by_type="admin", created_by__in=admin_ids)
            )

        elif user.user_type == "admin" and user_created_id:
            base_queryset = base_queryset.filter(
                created_by_type="admin",
                created_by=str(user_created_id)
            )

        return base_queryset.order_by('-category_id')
    
    def handle_validation_error(self, exc):
        if isinstance(exc.detail, dict):
            key = next(iter(exc.detail))
            message = exc.detail[key][0] if isinstance(exc.detail[key], list) else exc.detail[key]
        else:
            message = str(exc.detail)

        return Response({
            "success": False,
            "message": message
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        category_name = request.data.get('category_name', '').strip()
        user = request.user

        category_module = ModulePermission.objects.filter(
            module__iexact="Category"
        ).only("module_id").first()

        if not category_module:
            return Response(
                {"success": False, "message": "Course Categories module not found"},
                status=200
            )

        if not has_permission(user, module_id=category_module.module_id, actions=["create"]):
            return Response(
                {"success": False, "message": "You do not have permission"},
                status=200
            )

        serializer = self.get_serializer(data=request.data)

        # Single optimized query
        existing = CourseCategory.objects.filter(
            category_name__iexact=category_name
        ).only("category_id", "is_archived").first()

        if existing and not existing.is_archived:
            return Response({
                "success": False,
                "message": f"Category '{category_name}' already exists."
            }, status=status.HTTP_200_OK)

        if existing and existing.is_archived:
            existing.is_archived = False
            existing.save(update_fields=["is_archived"])

            serializer = self.get_serializer(existing)

            return Response({
                "success": True,
                "message": f"Category '{category_name}' created successfully (reactivated).",
                "data": serializer.data
            }, status=status.HTTP_200_OK)

        if not serializer.is_valid():
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."
            return Response({
                "success": False,
                "message": error_message
            }, status=status.HTTP_200_OK)

        serializer.save()

        return Response({
            "success": True,
            "message": f"Category '{category_name}' created successfully.",
            "data": serializer.data
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        user = request.user
        
        # Ensure module_id points to Course Categories
        category_module = ModulePermission.objects.filter(module__iexact="Category").first()
        if not category_module:
            return Response({"success": False, "message": "Course Categories module not found"}, status=200)

        if not has_permission(user, module_id=category_module.module_id, actions=["update"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)
        
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial, context={'request': request})

        if not serializer.is_valid():
            # Extract the first error message
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."

            return Response({
                "message": error_message,
                "success": False
            }, status=status.HTTP_200_OK)
        
        # Save notes if provided in request
        notes_text = request.data.get("notes")
        if notes_text:
            mixin = NotesMixin()
            mixin.save_notes(instance, notes_text, request=request)

        self.perform_update(serializer)
        return Response({
            "success": True,
            "message": "Category updated successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'], url_path='archive')
    def archive_category(self, request, *args, **kwargs):
        category = self.get_object()
        category.is_archived = True
        category.save()

        return Response({
            "success": True,
            "message": f"Category '{category.category_name}' deleted successfully."
        }, status=status.HTTP_200_OK)

class CourseViewSet(LoggingMixin, viewsets.ModelViewSet):
    """
    Production-grade ViewSet for managing Courses.
    Handles standard CRUD operations, custom role-based scoping, 
    auto-created bootcamp courses, and syllabus details.
    """
    queryset = Course.objects.filter(is_archived=False)
    serializer_class = CourseSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    lookup_field = "course_id"
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    # ------------------------------------------------------------------
    # ROLE-BASED FILTERS (SUPPORTING AUTO-CREATED BOOTCAMP COURSES)
    # ------------------------------------------------------------------
    def _get_role_filters(self, user):
        """
        Builds role-based access queries.
        Includes courses auto-created via Bootcamps/Webinars.
        """
        user_type = getattr(user, "user_type", None)
        filters = Q()

        if user_type == "super_admin":
            super_admin_id = str(getattr(user, "user_id", ""))

            admin_ids = list(
                Trainer.objects.filter(
                    created_by=super_admin_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )
            admin_ids = [str(i) for i in admin_ids]

            filters = (
                Q(created_by_type="super_admin", created_by=super_admin_id) |
                Q(created_by_type="admin", created_by__in=admin_ids) |
                # Support Bootcamp auto-created courses
                Q(notes__icontains="Auto-created") |
                Q(created_by__isnull=True)
            )

        elif user_type == "admin":
            admin_id = str(getattr(user, "trainer_id", ""))

            super_admin_id = Trainer.objects.filter(
                trainer_id=admin_id,
                is_archived=False
            ).values_list("created_by", flat=True).first()

            if super_admin_id:
                super_admin_id = str(super_admin_id)

            filters = (
                Q(created_by_type="admin", created_by=admin_id) |
                Q(created_by_type="super_admin", created_by=super_admin_id) |
                # Support Bootcamp auto-created courses
                Q(notes__icontains="Auto-created") |
                Q(created_by__isnull=True)
            )

        return filters

    def get_queryset(self):
        category_id = self.request.query_params.get("course_category")

        queryset = (
            Course.objects
            .filter(is_archived=False)
            .select_related("course_category")
        )

        role_filters = self._get_role_filters(self.request.user)
        queryset = queryset.filter(role_filters)

        if category_id:
            queryset = queryset.filter(course_category_id=category_id)

        return queryset.order_by("-course_id")

    # ------------------------------------------------------------------
    # LIST
    # ------------------------------------------------------------------
    def list(self, request, *args, **kwargs):
        try:
            queryset = self.get_queryset()
            filters = self._get_role_filters(request.user)

            category_qs = (
                CourseCategory.objects
                .filter(is_archived=False, status=True)
                .filter(filters)
            )

            category_data = CourseCategorySerializer(category_qs, many=True).data
            serializer = CourseListSerializer(queryset, many=True)

            if not serializer.data:
                return Response({
                    "success": False,
                    "message": "No courses found for the selected filter.",
                    "categories": category_data,
                    "currencies": CURRENCIES,
                    "data": []
                }, status=status.HTTP_200_OK)

            return Response({
                "success": True,
                "message": "Courses fetched successfully.",
                "data": serializer.data,
                "categories": category_data,
                "currencies": CURRENCIES
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"[CourseViewSet] List Error: {str(e)}", exc_info=True)
            return Response({
                "success": False,
                "message": f"An error occurred while fetching courses: {str(e)}"
            }, status=status.HTTP_200_OK)


    # ------------------------------------------------------------------
    # CREATE
    # ------------------------------------------------------------------
    def create(self, request, *args, **kwargs):
        user = request.user

        # Module Permission Check
        courses_module = ModulePermission.objects.filter(module__iexact="Course").first()
        if not courses_module:
            return Response({"success": False, "message": "Courses module configuration not found"}, status=status.HTTP_200_OK)

        if not has_permission(user, module_id=courses_module.module_id, actions=["create"]):
            return Response({"success": False, "message": "You do not have permission to create courses"}, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."
            return Response({
                "message": error_message,
                "success": False
            }, status=status.HTTP_200_OK)

        with transaction.atomic():
            self.perform_create(serializer)
            instance = serializer.instance

            # Process duration payload array if present
            duration = request.data.get("duration_list[0][duration]")
            duration_type = request.data.get("duration_list[0][duration_type]")

            if duration and duration_type:
                instance.duration = duration
                instance.duration_type = duration_type
                instance.save(update_fields=["duration", "duration_type"])

        response_serializer = self.get_serializer(instance)

        return Response({
            "message": "Course added successfully",
            "success": True,
            "data": response_serializer.data
        }, status=status.HTTP_201_CREATED)

    # ------------------------------------------------------------------
    # UPDATE / PARTIAL UPDATE
    # ------------------------------------------------------------------
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        user = request.user

        courses_module = ModulePermission.objects.filter(module__iexact="Course").first()
        if not courses_module:
            return Response({"success": False, "message": "Courses module not found"}, status=status.HTTP_200_OK)

        if not has_permission(user, module_id=courses_module.module_id, actions=["update"]):
            return Response({"success": False, "message": "You do not have permission to update courses"}, status=status.HTTP_200_OK)

        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial, context={'request': request})

        if not serializer.is_valid():
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."
            return Response({
                "message": error_message,
                "success": False,
            }, status=status.HTTP_200_OK)

        validated_data = serializer.validated_data
        new_status = validated_data.get("status", instance.status)
        new_category = validated_data.get("course_category", instance.course_category)

        # Validate category state prior to activation
        if new_status == "Active":
            if not new_category or getattr(new_category, "is_archived", False):
                return Response({
                    "success": False,
                    "message": "The category for this course has been archived/deleted. Please assign a valid category before activating."
                }, status=status.HTTP_200_OK)

            if not getattr(new_category, "status", False):
                return Response({
                    "success": False,
                    "message": f"Cannot activate this course because its category '{getattr(new_category, 'category_name', '')}' is inactive."
                }, status=status.HTTP_200_OK)

        with transaction.atomic():
            # Save notes if present
            notes_text = request.data.get("notes")
            if notes_text:
                mixin = NotesMixin()
                mixin.save_notes(instance, notes_text, request=request)

            self.perform_update(serializer)
            instance = serializer.instance

            # Process duration payload array if present
            duration = request.data.get("duration_list[0][duration]")
            duration_type = request.data.get("duration_list[0][duration_type]")

            if duration and duration_type:
                instance.duration = duration
                instance.duration_type = duration_type
                instance.save(update_fields=["duration", "duration_type"])

        response_serializer = self.get_serializer(instance)

        return Response({
            "message": "Course updated successfully",
            "success": True,
            "data": response_serializer.data
        }, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # CUSTOM ACTIONS
    # ------------------------------------------------------------------
    @action(detail=True, methods=['get'], url_path='batches')
    def get_batches(self, request, *args, **kwargs):
        course = self.get_object()
        batches = NewBatch.objects.filter(
            course=course,
            is_archived=False,
            status=True
        ).distinct()

        serializer = NewBatchSerializer(batches, many=True)
        return Response({
            "success": True,
            "message": f"Batches for course '{course.course_name}' fetched successfully.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'], url_path='archive')
    def archive_course(self, request, *args, **kwargs):
        course = self.get_object()
        course.is_archived = True
        course.save(update_fields=["is_archived"])

        return Response({
            "success": True,
            "message": f"Course '{course.course_name}' archived successfully."
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="syllabus")
    def syllabus(self, request, *args, **kwargs):
        course = self.get_object()

        items = (
            Syllabus.objects
            .filter(course=course)
            .select_related("course")
            .only(
                "id",
                "course",
                "file",
                "file_name",
                "file_type",
                "file_size",
                "title",
                "date",
                "created_at",
                "updated_at",
                "course__course_id",
                "course__course_name",
            )
            .order_by("-created_at")
        )

        serializer = SyllabusSerializer(
            items,
            many=True,
            context={"request": request}
        )

        return Response({
            "success": True,
            "message": "Syllabus fetched successfully.",
            "data": serializer.data,
        }, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # CONTEXT OVERRIDE
    # ------------------------------------------------------------------
    def get_serializer_context(self):
        context = super().get_serializer_context()
        request = self.request
        student = None

        if hasattr(request, "user") and request.user.is_authenticated:
            if getattr(request.user, "user_type", "") == "student":
                student = Student.objects.filter(
                    student_id=getattr(request.user, "student_id", None),
                    is_archived=False
                ).first()
            else:
                student_id = request.query_params.get("student_id")
                course_id = self.kwargs.get("course_id")

                if student_id and course_id:
                    student = Student.objects.filter(
                        student_id=student_id,
                        is_archived=False,
                        new_batches__course__course_id=course_id,
                        new_batches__is_archived=False,
                        new_batches__status=True,
                    ).distinct().first()

        context["student"] = student
        return context

   
    
class CourseVideoViewSet(viewsets.ModelViewSet):
    serializer_class = CourseVideoSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):

        user = self.request.user
        course_id = self.kwargs.get('course_id')

        qs = CourseVideo.objects.filter(
            is_archived=False
        ).order_by('-id')

        if course_id:
            qs = qs.filter(course=course_id)

        return qs
    def get_object(self):

        course_id = self.kwargs.get('course_id')
        video_id = self.kwargs.get('video_id')

        return get_object_or_404(
            CourseVideo,
            course=course_id,
            id=video_id,
            is_archived=False
        )
    
    
    # LIST
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        serializer = self.get_serializer(
            queryset,
            many=True,
            context={"request": request}
        )

        return Response({
            "success": True,
            "message": "Course videos retrieved successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    # CREATE
    def create(self, request, *args, **kwargs):

        course_id = self.kwargs.get('course_id')

        try:
            course = Course.objects.get(
                course_id=course_id
            )

        except Course.DoesNotExist:
            return Response({
                "success": False,
                "message": "Course not found"
            }, status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(
            data=request.data
        )

        if serializer.is_valid():

            video = serializer.save(
                course=course
            )

            return Response({
                "success": True,
                "message": "Course video created successfully",
                "data": CourseVideoSerializer(
                    video,
                    context={"request": request}
                ).data
            }, status=status.HTTP_201_CREATED)

        formatted = []

        for field, msgs in serializer.errors.items():

            for msg in msgs:

                if str(msg).startswith("This"):
                    formatted.append(f"{field} is required")
                else:
                    formatted.append(f"{field} {msg}")

        return Response({
            "success": False,
            "message": " | ".join(formatted)
        }, status=status.HTTP_200_OK)
    # UPDATE
    def update(self, request, *args, **kwargs):

        partial = kwargs.pop('partial', False)

        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=partial
        )

        if serializer.is_valid(raise_exception=True):

            self.perform_update(serializer)

            return Response({
                "success": True,
                "message": "Course video updated successfully",
                "data": serializer.data
            }, status=status.HTTP_200_OK)

        return Response({
            "success": False,
            "message": "Validation failed",
            "errors": serializer.errors
        }, status=status.HTTP_200_OK)

    # DELETE (SOFT DELETE)
    def destroy(self, request, *args, **kwargs):

        instance = self.get_object()

        instance.is_archived = True
        instance.save()

        return Response({
            "success": True,
            "message": "Course video deleted successfully"
        }, status=status.HTTP_200_OK)
    

class TopicViewSet(LoggingMixin, viewsets.ModelViewSet):
    serializer_class = TopicSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        course_id = self.kwargs.get('course_id')
        try:
            course = Course.objects.get(course_id=course_id)
        except Course.DoesNotExist:
            raise NotFound("Course not found or deleted.")
        return Topic.objects.filter(course=course, is_archived=False).order_by('created_date')

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "success": True,
            "message": "Topics fetched successfully.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        try:
            course_id = self.kwargs.get("course_id")

            try:
                course = Course.objects.get(course_id=course_id, is_archived=False)
            except Course.DoesNotExist:
                return Response(
                    {"success": False, "message": "Course not found or deleted."},
                    status=status.HTTP_200_OK
                )

            

            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            

            serializer.save(course=course)

            

            return Response(
                {
                    "success": True,
                    "message": "Topic created successfully.",
                    "data": serializer.data
                },
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            
            raise
    
    # Combine update and partial_update here
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)  # Check if partial update was requested

        instance = self.get_object()  # fetch existing object
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return Response({
            "success": True,
            "message": "Topic updated successfully",
            "data": serializer.data
        }, status=status.HTTP_200_OK)



    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            instance.delete()

            return Response({
                "success": True,
                "message": "Topic deleted successfully."
            }, status=status.HTTP_200_OK)

        except Exception as e:
            print(traceback.format_exc())

            return Response({
                "success": False,
                "message": str(e),
                "traceback": traceback.format_exc(),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)   
            
class StudentTopicStatusViewSet(LoggingMixin, viewsets.ModelViewSet):
    serializer_class = StudentTopicStatusSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]

    def get_queryset(self):
        student_id = self.request.query_params.get('student_id')
        course_id = self.request.query_params.get('course_id')

        queryset = StudentTopicStatus.objects.select_related('student', 'topic', 'topic__course')

        if student_id:
            queryset = queryset.filter(student__student_id=student_id, student__is_archived=False)

        if course_id:
            queryset = queryset.filter(topic__course__course_id=course_id, topic__is_archived=False)

        return queryset.order_by('topic__created_date')

    def list(self, request, *args, **kwargs):
        course_id = self.kwargs.get('course_id')
        student_id = self.kwargs.get('student_id')

        # Validate course
        course = Course.objects.filter(course_id=course_id).first()
        if not course:
            return Response({
                "success": False,
                "message": "Course not found or deleted.",
                "all_topics": [],
                "completed_topics": []
            }, status=status.HTTP_200_OK)

        # Validate student
        student = Student.objects.filter(student_id=student_id, is_archived=False).first()
        if not student:
            return Response({
                "success": False,
                "message": "Student not found or archived.",
                "all_topics": [],
                "completed_topics": []
            }, status=status.HTTP_200_OK)

        # Get all topics for the course
        topics = Topic.objects.filter(course=course, is_archived=False).order_by('created_date')

        # Get completed statuses for student (not just IDs now)
        completed_statuses = StudentTopicStatus.objects.filter(
            student=student,
            topic__in=topics,
            status=True
        ).select_related('topic', 'topic__course')

        # Serialize completed topic statuses
        completed_serializer = StudentTopicStatusSerializer(completed_statuses, many=True)

        # Get topic_ids marked as completed
        completed_topic_ids = set(completed_statuses.values_list('topic_id', flat=True))

        # Build all_topics list
        all_topics = []
        for topic in topics:
            all_topics.append({
                "topic_id": topic.topic_id,
                "title": topic.title,
                "description": topic.description,
                "created_date": topic.created_date.strftime('%Y-%m-%d %H:%M:%S') if topic.created_date else None,
                "is_completed": topic.topic_id in completed_topic_ids
            })

        if not student:
            return Response({
                "success": False,
                "message": "Student not found or archived.",
                "all_topics": all_topics,
                "completed_topics": []
            }, status=status.HTTP_200_OK)

        return Response({
            "success": True,
            "message": "Topics with completion status fetched successfully.",
            "all_topics": all_topics,
            "completed_topics": completed_serializer.data
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        data = request.data.copy()

        # Try to get student_id and topic from URL kwargs if not in data
        student_id = data.get('student_id') or self.kwargs.get('student_id')
        topic_id = data.get('topic') or self.kwargs.get('topic')

        if not student_id or not topic_id:
            raise ValidationError("Both student_id and topic are required.")

        try:
            student = Student.objects.get(student_id=student_id, is_archived=False)
            topic = Topic.objects.get(pk=topic_id, is_archived=False)
        except Student.DoesNotExist:
            return Response({
                "success": False,
                "message": "Student with this student_id not found."
            }, status=status.HTTP_200_OK)
        except Topic.DoesNotExist:
            return Response({
                "success": False,
                "message": "Topic not found."
            }, status=status.HTTP_200_OK)

        # Prepare data for serializer
        data['student'] = student.pk
        data['topic'] = topic.pk

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        return Response({
            "success": True,
            "message": "Topic created successfully.",
            "data": serializer.data
        }, status=status.HTTP_201_CREATED)

class CourseSyllabusViewSet(viewsets.ViewSet):
    """
    Routes (add to urls.py):
 
    path('courses/<str:course_id>/syllabus',
         CourseSyllabusViewSet.as_view({'get': 'list', 'post': 'create'})),
 
    path('courses/<str:course_id>/syllabus/<int:syllabus_id>',
         CourseSyllabusViewSet.as_view({'delete': 'destroy', 'patch': 'update'})),
    """
 
    permission_classes = [IsAuthenticated]  # adjust to match your existing permission setup
    parser_classes = [MultiPartParser, FormParser]
 
    def list(self, request, course_id=None):
        # select_related('course') avoids a separate query per item if the
        # serializer ever needs course fields (e.g. course name).
        # .only() limits the columns pulled back to what's actually
        # serialized, cutting payload size read from the DB.
        items = (
            Syllabus.objects
            .filter(course_id=course_id)
            .select_related('course')
            .only(
                "id",
                "course",
                "file",
                "file_name",
                "file_type",
                "file_size",
                "title",
                "date",
                "created_at",
                "updated_at",
                "course__course_id",
                "course__course_name"
                )
        )
        serializer = SyllabusSerializer(items, many=True, context={'request': request})
        return Response({
            'success': True,
            'data': serializer.data
        })
 
    def create(self, request, course_id=None):
        # Ensure the course actually exists before attaching a syllabus item to it
        try:
            Course.objects.get(pk=course_id)
        except Course.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Course not found'},
                status=status.HTTP_404_NOT_FOUND
            )
 
        serializer = SyllabusCreateSerializer(
            data=request.data,
            context={'course_id': course_id}
        )
        if serializer.is_valid():
            instance = serializer.save()
            output = SyllabusSerializer(instance, context={'request': request})
            return Response(
                {'success': True, 'data': output.data},
                status=status.HTTP_201_CREATED
            )
 
        return Response(
            {'success': False, 'message': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )
 
    def update(self, request, course_id=None, syllabus_id=None):
        try:
            instance = Syllabus.objects.get(pk=syllabus_id, course_id=course_id)
        except Syllabus.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Syllabus item not found'},
                status=status.HTTP_404_NOT_FOUND
            )
 
        serializer = SyllabusCreateSerializer(
            instance,
            data=request.data,
            partial=True,
            context={'course_id': course_id}
        )
        if serializer.is_valid():
            updated = serializer.save()
            output = SyllabusSerializer(updated, context={'request': request})
            return Response({'success': True, 'data': output.data})
 
        return Response(
            {'success': False, 'message': serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )
 
    def destroy(self, request, course_id=None, syllabus_id=None):
        try:
            instance = Syllabus.objects.get(pk=syllabus_id, course_id=course_id)
        except Syllabus.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Syllabus item not found'},
                status=status.HTTP_404_NOT_FOUND
            )
 
        instance.file.delete(save=False)  # remove the actual file from storage
        instance.delete()
        return Response({'success': True, 'message': 'Syllabus item deleted'})
 