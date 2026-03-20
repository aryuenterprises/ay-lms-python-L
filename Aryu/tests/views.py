from .models import *
from .serializers import *
from aryuapp.auth import CustomJWTAuthentication
from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated 
from aryuapp.mixins import LoggingMixin
from rest_framework.decorators import action
from aryuapp.models import ModulePermission
from aryuapp.views import has_permission
from django.utils import timezone
from django.contrib.auth.hashers import *
from django.db.models import Q, Count, Prefetch
from aryuapp.models import Trainer
from courses.models import Course
# Create your views here.


class TestViewSet(LoggingMixin, viewsets.ModelViewSet):
    serializer_class = TestSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    queryset = Test.objects.all()
    
    def get_queryset(self):
        user = self.request.user
        user_type = getattr(user, "user_type", "").lower()
        admin_trainer_id = getattr(user, "trainer_id", None)
        user_created_id = getattr(user, "user_id", None) if user_type == "super_admin" else admin_trainer_id

        # Super admin: get all admin IDs created by this super admin
        admin_ids = []
        if user_type == "super_admin" and user_created_id:
            admin_ids = list(
                Trainer.objects.filter(
                    created_by=user_created_id,
                    created_by_type="super_admin",
                    is_archived=False
                ).values_list("trainer_id", flat=True)
            )

        # Base queryset
        qs = Test.objects.filter(is_archived=False)

        # Apply filtering
        if user_type == "admin" and admin_trainer_id:
            qs = qs.filter(created_by=admin_trainer_id)
        elif user_type == "super_admin":
            qs = qs.filter(
                Q(created_by=user_created_id, created_by_type="super_admin") |
                Q(created_by__in=admin_ids, created_by_type="admin")
            )

        return qs.order_by('-test_id')

    def list(self, request, *args, **kwargs):
        try:
            # Annotate each test with the count of non-archived questions
            queryset = self.get_queryset().annotate(
                question_count=Count('test_questions', filter=Q(test_questions__is_archived=False))
            )

            serializer = self.get_serializer(queryset, many=True)

            user = self.request.user
            user_type = getattr(user, "user_type", "").lower()
            admin_trainer_id = getattr(user, "trainer_id", None)
            user_created_id = getattr(user, "user_id", None) if user_type == "super_admin" else admin_trainer_id

            # ---------------- Courses Filtering ----------------
            all_courses = Course.objects.filter(is_archived=False, status__iexact='Active')

            if user_type == "admin" and admin_trainer_id:
                all_courses = all_courses.filter(created_by=admin_trainer_id)
            elif user_type == "super_admin" and user_created_id:
                # Get all admin IDs created by this super admin
                admin_ids = list(
                    Trainer.objects.filter(
                        created_by=user_created_id,
                        created_by_type="super_admin",
                        is_archived=False
                    ).values_list("trainer_id", flat=True)
                )
                all_courses = all_courses.filter(
                    Q(created_by=user_created_id, created_by_type="super_admin") |
                    Q(created_by__in=admin_ids, created_by_type="admin")
                )
            elif user_type == "trainer":
                    # Trainer belongs to an admin
                trainer_id = getattr(user, "trainer_id", None)
                if trainer_id:
                    # Find the admin who created this trainer
                    trainer_obj = Trainer.objects.filter(trainer_id=trainer_id).first()
                    if trainer_obj and trainer_obj.created_by_type == "admin":
                        admin_id = trainer_obj.created_by
                        courses = courses.filter(created_by=admin_id, created_by_type="admin")
                    elif trainer_obj and trainer_obj.created_by_type == "super_admin":
                        super_admin_id = trainer_obj.created_by
                        courses = courses.filter(created_by=super_admin_id, created_by_type="super_admin")

            elif user_type == "student":
                student_id = getattr(user, "student_id", None)
                if student_id:
                    # Get the admin/super_admin who created their batch/trainer
                    batch_trainer_qs = NewBatch.objects.filter(students=student_id)
                    # get all unique admins
                    admin_ids = set()
                    for bt in batch_trainer_qs:
                        if bt.trainer.created_by_type == "admin":
                            admin_ids.add(bt.trainer.created_by)
                        elif bt.trainer.created_by_type == "super_admin":
                            admin_ids.add(bt.trainer.created_by)

                    courses = courses.filter(Q(created_by__in=admin_ids))


            all_courses = all_courses.values('course_id', 'course_name')

            if queryset.exists():
                # Add question_count to each serialized test
                data_with_question_count = []
                for item, test in zip(serializer.data, queryset):
                    item['question_count'] = test.question_count
                    data_with_question_count.append(item)

                return Response({
                    "success": True,
                    'message': "Data retrieved successfully.",
                    "data": data_with_question_count,
                    "courses": list(all_courses)
                }, status=200)

            return Response({
                "success": False,
                "message": "No data found.",
                "courses": list(all_courses)
            }, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        
        user = request.user
        
        # Ensure module_id points to Test
        test_module = ModulePermission.objects.filter(module__iexact="Assessment").first()
        if not test_module:
            return Response({"success": False, "message": "Test module not found in permissions"}, status=200)

        if not has_permission(user, module_id=test_module.module_id, actions=["create"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)

        if not serializer.is_valid():
            # Extract the first error message
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."

            return Response({
                "message": error_message,
                "success": False
            }, status=status.HTTP_200_OK)

        test = serializer.save()
        return Response({
            "success": True,
            "message": "Test created successfully.",
            "data": self.get_serializer(test).data
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        
        user = request.user
        
        # Ensure module_id points to Test
        test_module = ModulePermission.objects.filter(module__iexact="Assessment").first()
        if not test_module:
            return Response({"success": False, "message": "Test module not found"}, status=200)

        if not has_permission(user, module_id=test_module.module_id, actions=["update"]):
            return Response({"success": False, "message": "You do not have permission"}, status=200)
        
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if not serializer.is_valid():
            # Extract the first error message
            error_messages = flatten_errors(serializer.errors)
            error_message = ". ".join(error_messages) + "."

            return Response({
                "message": error_message,
                "success": False
            }, status=status.HTTP_200_OK)

        test = serializer.save()
        return Response({
            "success": True,
            "message": "Test updated successfully.",
            "data": self.get_serializer(test).data
        })

    @action(detail=True, methods=['patch'], url_path='questions')
    def test_questions(self, request, *args, **kwargs):
        try:
            test = self.get_object()  # get the Test instance
        except Test.DoesNotExist:
            return Response({"success": False, "message": "Test not found"}, status=200)

        # Use the correct related_name
        questions = test.test_questions.all().filter(is_archived=False)

        return Response({
            "success": True,
            "test": {
                "test_id": test.test_id,
                "test_name": test.test_name,
                "description": test.description,
                "total_marks": test.total_marks,
                "pass_mark": test.pass_mark
            },
            "questions": TestQuestionsSerializer(questions, many=True).data
        }, status=200)

    @action(detail=False, methods=['get'], url_path=r'(?P<test_id>\d+)/student/(?P<student_id>[^/.]+)/result')
    def student_test_result(self, request, test_id=None, student_id=None):
        try:
            student = Student.objects.filter(student_id=student_id).first()
            if not student:
                return Response({"success": False, "message": "Student not found"}, status=200)

            test = Test.objects.filter(test_id=test_id, is_archived=False).first()
            if not test:
                return Response({"success": False, "message": "Test not found"}, status=200)

            # Fetch answers for this student & test
            answers = StudentAnswers.objects.filter(student_id=student, test_id=test)

            # Fetch finalized score
            test_result = TestResult.objects.filter(student_id=student, test_id=test).first()

            # Build response
            questions_data = []
            for ans in answers.select_related("question_id"):
                question = ans.question_id
                question_type = question.type  # or 'type' depending on your field

                # Determine correct answer and student answer based on type
                if question_type == "mcq":
                    correct_answer = question.mcq_correct_option
                    student_answer = ans.selected_option
                    options = question.options
                    written_answer = None
                elif question_type == "written":
                    correct_answer = question.written_answer
                    student_answer = ans.written_answer
                    options = None
                    written_answer = question.written_answer

                questions_data.append({
                    "question_id": question.question_id,
                    "question": question.question,
                    "type": question_type,
                    "options": options,
                    "correct_answer": correct_answer,
                    "student_answer": student_answer,
                    "is_correct": ans.is_correct,
                    "marks": question.marks,
                })

            return Response({
                "success": True,
                "student_id": student.student_id,
                "registration_id": student.registration_id,
                "test_id": test.test_id,
                "test_name": test.test_name,
                "total_marks": test.total_marks,
                "score": test_result.score if test_result else None,
                "questions": questions_data
            }, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    @action(detail=False, methods=['get'], url_path=r'course/(?P<course_id>[^/.]+)')
    def tests_by_course(self, request, course_id=None):
        try:
            # -------------------------
            # Validate Course
            # -------------------------
            course = Course.objects.filter(course_id=course_id, is_archived=False).first()
            if not course:
                return Response({"success": False, "message": "Course not found"}, status=200)

            user_type = getattr(request.user, "user_type", None)
            employee_id = getattr(request.user, "employee_id", None)
            employer_id = getattr(request.user, "employer_id", None)
            trainer_id = getattr(request.user, "trainer_id", None)
            student_id = getattr(request.user, "student_id", None)

            # -------------------------
            # Base Tests
            # -------------------------
            tests = Test.objects.filter(
                course_id=course,
                is_archived=False
            ).prefetch_related(
                Prefetch(
                    'test_questions',
                    queryset=TestQuestions.objects.filter(is_archived=False),
                    to_attr='active_questions'
                )
            )

            data = []  # final list

            # ============================================================
            # CASE 1 : STUDENT
            # ============================================================
            if user_type == "student":
                student = Student.objects.filter(student_id=student_id).first()
                if not student:
                    return Response({"success": False, "message": "Student not found"}, status=200)

                for test in tests:
                    answers_qs = StudentAnswers.objects.filter(
                        student_id=student.student_id,
                        test_id=test.test_id
                    )

                    attempted = answers_qs.exists()
                    correction_done = TestResult.objects.filter(
                        student_id=student,
                        test_id=test.test_id
                    ).exists() if attempted else False

                    # Get question snapshot
                    if attempted:
                        questions_data = [
                            {
                                "question_id": ans.question_id.question_id if ans.question_id else None,
                                "question": ans.question_text,
                                "type": ans.question_id.type if ans.question_id else None,
                                "options": ans.options_snapshot,
                                "correct_answer": ans.correct_answer_snapshot
                            }
                            for ans in answers_qs.select_related("question_id")
                        ]
                    else:
                        questions_data = TestQuestionsSerializer(test.active_questions, many=True).data

                    data.append({
                        "test_id": test.test_id,
                        "test_name": test.test_name,
                        "description": test.description,
                        "course_name": test.course_id.course_name,
                        "course_id": test.course_id.course_id,
                        "duration": test.duration,
                        "total_marks": test.total_marks,
                        "question_count": len(test.active_questions),
                        "questions": questions_data,
                        "test_completion": attempted,
                        "correction_done": correction_done
                    })

            # ============================================================
            # CASE 2 : TUTOR
            # ============================================================

            elif user_type == "tutor":

                # Fetch students ONLY from NewBatch
                assigned_students = Student.objects.filter(
                    new_batches__trainer__employee_id=employee_id,
                    new_batches__course_id=course_id,
                    new_batches__status=True,
                    new_batches__is_archived=False,
                    is_archived=False
                ).distinct()

                for test in tests:
                    students_data = []

                    for student in assigned_students:
                        answers_qs = StudentAnswers.objects.filter(student_id=student, test_id=test.test_id)
                        if not answers_qs.exists():
                            continue

                        correction_done = TestResult.objects.filter(
                            student_id=student,
                            test_id=test.test_id
                        ).exists()

                        students_data.append({
                            "registration_id": student.registration_id,
                            "student_id": student.student_id,
                            "student_name": f"{student.first_name} {student.last_name}",
                            "attempted": True,
                            "answers": StudentAnswersSerializer(answers_qs, many=True).data,
                            "correction_done": correction_done
                        })

                    if students_data:
                        data.append({
                            "test_id": test.test_id,
                            "test_name": test.test_name,
                            "description": test.description,
                            "course_name": test.course_id.course_name,
                            "course_id": test.course_id.course_id,
                            "duration": test.duration,
                            "total_marks": test.total_marks,
                            "question_count": len(test.active_questions),
                            "students": students_data
                        })


            # ============================================================
            # CASE 3 : EMPLOYER
            # ============================================================
            elif user_type == "employer":

                students = Student.objects.filter(
                    new_batches__course_id=course_id,
                    new_batches__status=True,
                    new_batches__is_archived=False,
                    employer_id=employer_id,
                    is_archived=False
                ).distinct()

                for test in tests:
                    students_data = []

                    for student in students:
                        answers_qs = StudentAnswers.objects.filter(student_id=student, test_id=test.test_id)
                        if not answers_qs.exists():
                            continue

                        answers_data = []
                        questions_data = []

                        for ans in answers_qs.select_related("question_id"):
                            answers_data.append({
                                "answer_id": ans.answer_id,
                                "question_id": ans.question_id.question_id if ans.question_id else None,
                                "answer_text": ans.written_answer or ans.selected_option,
                                "submitted_at": ans.submitted_at.strftime('%Y-%m-%d %H:%M:%S')
                            })
                            questions_data.append({
                                "question_id": ans.question_id.question_id if ans.question_id else None,
                                "question": ans.question_text,
                                "type": ans.question_id.type if ans.question_id else None,
                                "options": ans.options_snapshot,
                                "correct_answer": ans.correct_answer_snapshot
                            })

                        correction_done = TestResult.objects.filter(
                            student_id=student,
                            test_id=test.test_id
                        ).exists()

                        students_data.append({
                            "registration_id": student.registration_id,
                            "student_id": student.student_id,
                            "student_name": f"{student.first_name} {student.last_name}",
                            "attempted": True,
                            "answers": answers_data,
                            "questions": questions_data,
                            "correction_done": correction_done
                        })

                    if students_data:
                        data.append({
                            "test_id": test.test_id,
                            "test_name": test.test_name,
                            "description": test.description,
                            "course_name": test.course_id.course_name,
                            "course_id": test.course_id.course_id,
                            "duration": test.duration,
                            "total_marks": test.total_marks,
                            "question_count": len(test.active_questions),
                            "students": students_data
                        })


            # ============================================================
            # CASE 4 : ADMIN + SUPER ADMIN
            # ============================================================
            elif user_type in ["admin", "super_admin"]:
                
                if user_type == "super_admin":
                    admin_tests = tests

                    admin_students = Student.objects.filter(
                        new_batches__course_id=course_id,
                        new_batches__status=True,
                        new_batches__is_archived=False,
                        is_archived=False
                    ).distinct()

                else:
                    admin_tests = tests.filter(created_by=trainer_id)

                    admin_students = Student.objects.filter(
                        new_batches__trainer__trainer_id=trainer_id,
                        new_batches__course_id=course_id,
                        new_batches__status=True,
                        new_batches__is_archived=False,
                        is_archived=False
                    ).distinct()

                for test in admin_tests:
                    students_data = []

                    for student in admin_students:
                        answers_qs = StudentAnswers.objects.filter(student_id=student, test_id=test.test_id)
                        if not answers_qs.exists():
                            continue

                        answers_data = []
                        questions_data = []

                        for ans in answers_qs.select_related("question_id"):
                            answers_data.append({
                                "answer_id": ans.answer_id,
                                "question_id": ans.question_id.question_id if ans.question_id else None,
                                "answer_text": ans.written_answer or ans.selected_option,
                                "submitted_at": ans.submitted_at.strftime('%Y-%m-%d %H:%M:%S')
                            })
                            questions_data.append({
                                "question_id": ans.question_id.question_id if ans.question_id else None,
                                "question": ans.question_text,
                                "type": ans.question_id.type if ans.question_id else None,
                                "options": ans.options_snapshot,
                                "correct_answer": ans.correct_answer_snapshot
                            })

                        correction_done = TestResult.objects.filter(
                            student_id=student,
                            test_id=test.test_id
                        ).exists()

                        students_data.append({
                            "registration_id": student.registration_id,
                            "student_id": student.student_id,
                            "student_name": f"{student.first_name} {student.last_name}",
                            "attempted": True,
                            "answers": answers_data,
                            "questions": questions_data,
                            "correction_done": correction_done
                        })

                    if students_data:
                        data.append({
                            "test_id": test.test_id,
                            "test_name": test.test_name,
                            "description": test.description,
                            "course_name": test.course_id.course_name,
                            "course_id": test.course_id.course_id,
                            "duration": test.duration,
                            "total_marks": test.total_marks,
                            "question_count": len(test.active_questions),
                            "students": students_data
                        })

            else:
                return Response({"success": False, "message": "Role not supported"}, status=200)

            return Response({"success": True, "tests": data}, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)
        
    @action(detail=False, methods=['get'], url_path='<int:course_id>/<str:student_id>')
    def test_by_students(self, request, course_id=None, student_id=None):
        try:
            # 1. Validate course
            try:
                course = Course.objects.get(course_id=course_id, is_archived=False)
            except Course.DoesNotExist:
                return Response({"success": False, "message": "Course not found"}, status=200)

            # 2. Validate student
            try:
                student = Student.objects.get(student_id=student_id, is_archived=False)
            except Student.DoesNotExist:
                return Response({"success": False, "message": "Student not found"}, status=200)

            # 3. Fetch tests only for this course
            tests = Test.objects.filter(course_id=course, is_archived=False).prefetch_related(
                Prefetch(
                    "test_questions",
                    queryset=TestQuestions.objects.filter(is_archived=False),
                    to_attr="active_questions"
                )
            ).order_by("-test_id")

            data = []
            for test in tests:
                # answers for this student & test
                answers_qs = StudentAnswers.objects.filter(
                    student_id=student.student_id,
                    test_id=test.test_id
                )

                attempted = answers_qs.exists()

                correction_done = False
                                
                # Determine questions to show based on whether the student already attempted
                if attempted:
                    # Use snapshot from StudentAnswers
                    questions_data = []
                    for ans in answers_qs.select_related('question_id'):
                        questions_data.append({
                            "question_id": ans.question_id.question_id if ans.question_id else None,
                            "question": ans.question_text,
                            "type": ans.question_id.type if ans.question_id else None,
                            "options": ans.options_snapshot,
                            "correct_answer": ans.correct_answer_snapshot
                        })
                else:
                    # Student not attempted yet, show current questions
                    questions_data = TestQuestionsSerializer(test.active_questions, many=True).data
                    
                result = TestResult.objects.filter(student_id=student, test_id=test).first()
                correction_done = bool(result)
                trainer_name = None
                trainer_employee_id = None
                if result and result.evaluated_by:
                    trainer_name = result.evaluated_by.full_name
                    trainer_employee_id = result.evaluated_by.employee_id
                evaluated_at = result.evaluated_at if result else None

                # Keep all other fields as-is
                data.append({
                    "test_id": test.test_id,
                    "test_name": test.test_name,
                    "course_name": test.course_id.course_name,
                    'course_id': test.course_id.course_id,
                    "description": test.description,
                    "duration": test.duration,
                    "total_marks": test.total_marks,
                    "submitted_at": answers_qs.first().submitted_at.strftime('%Y-%m-%d %H:%M:%S') if attempted else None,
                    "evaluated_by": {
                        "employee_id": trainer_employee_id,
                        "full_name": trainer_name
                    },
                    "evaluated_at": evaluated_at.strftime('%Y-%m-%d %H:%M:%S') if evaluated_at else evaluated_at,
                    "question_count": len(test.active_questions),
                    "questions": questions_data,
                    "answers": StudentAnswersSerializer(answers_qs, many=True).data if attempted else [],
                    "test_completion": attempted,
                    "correction_done": correction_done
                })

            return Response({
                "success": True,
                "message": "Tests retrieved successfully",
                "registration_id": student.registration_id,
                "student_name": f"{student.first_name} {student.last_name}".strip(),
                "tests": data
            }, status=200)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)

    @action(
        detail=False,
        methods=['get'],
        url_path=r'<test_id>/student/<student_id>/answers'
    )
    def student_test_answers(self, request, test_id=None, student_id=None):
        """
        Get all questions of a test with student's submitted answers (snapshot).
        """
        # Get student
        student = Student.objects.filter(student_id=student_id).first()
        if not student:
            return Response({"success": False, "message": "Student not found"}, status=200)

        # Get test
        test = Test.objects.filter(pk=test_id, is_archived=False).first()
        if not test:
            return Response({"success": False, "message": "Test not found"}, status=200)

        # Get student's answers for this test
        answers = StudentAnswers.objects.filter(test_id=test, student_id=student).select_related('question_id')
        answers_map = {a.question_id_id: a for a in answers}

        # Build response using snapshot
        data = []
        for ans in answers:
            q_snapshot = {
                "question_id": ans.question_id.question_id if ans.question_id else None,
                "question": ans.question_text,               # snapshot of question text
                "type": ans.question_id.type if ans.question_id else None,
                "options": ans.options_snapshot,             # snapshot of options
                "marks": ans.marks_snapshot,
                "mcq_correct_answer": ans.correct_answer_snapshot,  # snapshot of correct answer
            }

            submitted_answer = {
                "answer_id": ans.answer_id,
                "selected_option": ans.selected_option,
                "written_answer": ans.written_answer,
                "is_correct": ans.is_correct,
            }

            data.append({
                "question": q_snapshot,
                "submitted_answer": submitted_answer
            })

        return Response({
            "success": True,
            "message": "Questions and answers retrieved successfully",
            "student": {
                "registration_id": student.registration_id,
                "student_id": student.student_id,
                "name": f"{student.first_name} {student.last_name}"
            },
            "test": {
                "test_id": test.test_id,
                "test_name": test.test_name,
            },
            "data": data
        }, status=200)

    def is_archived(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_archived = True
        instance.save()
        if instance.is_archived:
            return Response({ 'success': True ,'message': 'Test deleted successfully.'}, status=status.HTTP_200_OK)
        return Response({ 'success': False ,'message': 'Failed to delete test.'}, status=status.HTTP_200_OK)

class TestQuestionViewSet(LoggingMixin, viewsets.ModelViewSet):
    serializer_class = TestQuestionsSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    queryset = TestQuestions.objects.all()

    def get_queryset(self):
        return super().get_queryset().filter(is_archived=False).order_by('question_id')

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        if queryset.exists():
            return Response({"success": True, "message": "Data retrieved successfully.", "data": serializer.data}, status=200)
        return Response({"success": False, "message": "No data found."}, status=200)

    def create(self, request, *args, **kwargs):
        """
        Accepts either a single question or a list of questions.
        Each question can be MCQ or Written.
        """
        data = request.data
        is_list = isinstance(data, list)
        if not is_list:
            data = [data]

        created_questions = []

        for q_data in data:
            serializer = self.get_serializer(data=q_data)
            if serializer.is_valid():
                question = serializer.save()
                created_questions.append(serializer.data)
            else:
                # Use global flatten_errors function
                error_messages = flatten_errors(serializer.errors)
                error_message = ". ".join(error_messages) + "."

                return Response({
                    "success": False,
                    "message": error_message
                }, status=status.HTTP_200_OK)

        return Response({
            "success": True,
            "message": "Questions created successfully.",
            "data": created_questions
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
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
            "message": "Question updated successfully.",
            "data": self.get_serializer(instance).data
        }, status=status.HTTP_200_OK)

    def is_archived(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_archived = True
        instance.save()
        return Response({'success': True, 'message': 'Question archived successfully.'}, status=200)
    
class StudentAnswerViewSet(LoggingMixin, viewsets.ModelViewSet):
    serializer_class = StudentAnswersSerializer
    permission_classes = [IsAuthenticated]
    authentication_classes = [CustomJWTAuthentication]
    queryset = StudentAnswers.objects.all()

    def get_queryset(self):
        return super().get_queryset().order_by('answer_id')

    def create(self, request, *args, **kwargs):
        try:
            student_stu_id = getattr(request.user, "student_id", None)
            if not student_stu_id:
                return Response({"success": False, "message": "student_id missing in token"}, status=200)

            student = Student.objects.filter(student_id=student_stu_id).first()
            if not student:
                return Response({"success": False, "message": f"Student {student_stu_id} not found"}, status=200)

            data = request.data
            is_list = isinstance(data, list)
            if not is_list:
                data = [data]

            created_answers = []
            for ans_data in data:
                ans_data = ans_data.copy()
                ans_data['student_id'] = student.student_id
                ans_data['is_correct'] = False  # always false initially

                serializer = self.get_serializer(data=ans_data)
                try:
                    serializer.is_valid(raise_exception=True)
                except serializers.ValidationError as ve:
                    # Grab the first error message (clean version)
                    error_msg = " ".join([str(err) for errs in ve.detail.values() for err in errs])
                    return Response({"success": False, "message": error_msg}, status=400)

                answer = serializer.save()
                created_answers.append(self.get_serializer(answer).data)

            return Response({
                "success": True,
                "message": f"{len(created_answers)} Answer(s) submitted successfully.",
                "data": created_answers
            }, status=201)

        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=200)
        
class TestResultViewSet(LoggingMixin, viewsets.ModelViewSet):
    serializer_class = TestResultSerializer
    authentication_classes = [CustomJWTAuthentication]
    permission_classes = [IsAuthenticated]
    queryset = TestResult.objects.all()

    def get_queryset(self):
        return super().get_queryset().order_by('-result_id')

    def list(self, request, registration_id=None, *args, **kwargs):
        queryset = self.get_queryset().filter(student_id__registration_id=registration_id)
        serializer = self.get_serializer(queryset, many=True)
        if queryset.exists():
            return Response({"success": True, "message": "Data retrieved successfully.", "data": serializer.data}, status=200)
        return Response({"success": False, "message": f"No results found for student {registration_id}"}, status=200)

    @action(detail=False, methods=['post'], url_path='finalize/(?P<test_id>[^/.]+)/mark_and_finalize')
    def mark_and_finalize(self, request, test_id=None):
        try:
            data = request.data
            student_id = data.get("student_id")
            answers = data.get("answers", [])
            score = data.get("score")

            # 1. Update StudentAnswers correctness
            for ans in answers:
                answer_id = ans.get("answer_id")
                is_correct = ans.get("is_correct", False)
                StudentAnswers.objects.filter(
                    answer_id=answer_id,
                    test_id=test_id,
                    student_id__student_id=student_id
                ).update(is_correct=is_correct)

            # 2. Create/Update TestResult
            trainer = Trainer.objects.get(employee_id=request.user.employee_id)

            test_result, _ = TestResult.objects.update_or_create(
                student_id=Student.objects.get(student_id=student_id),
                test_id=Test.objects.get(test_id=test_id),
                defaults={
                    "score": score,
                    "evaluated_by": trainer,
                    "evaluated_at": timezone.now()
                }
            )

            return Response({
                "success": True,
                "message": "Result finalized successfully",
                "test_result_id": test_result.result_id,
                "score": test_result.score
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "success": False,
                "message": str(e)
            }, status=status.HTTP_200_OK)
