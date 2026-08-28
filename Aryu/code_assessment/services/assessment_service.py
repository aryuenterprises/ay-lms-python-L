"""
Assessment management and student progress calculation service.
Directly uses the existing aryuapp.Student model.
"""
import logging
from aryuapp.models import Student
from ..models import (
    CodingAssessment,
    CodeSubmission,
    AssessmentProblem,
    AssessmentAttempt,
)
from ..constants import STATUS_ACCEPTED

logger = logging.getLogger(__name__)


class AssessmentService:
    """
    Business logic for assessments, scoring, and course progress tracking.
    """

    @staticmethod
    def get_assessment_summary(assessment: CodingAssessment, student: Student) -> dict:
        """
        Calculates a student's progress, problems attempted, points scored, and completion status.
        """
        if not student:
            return {
                "assessment_id": assessment.id,
                "title": assessment.title,
                "total_problems": assessment.assessment_problems.count(),
                "problems_attempted": 0,
                "problems_solved": 0,
                "total_possible_points": sum(ap.points for ap in assessment.assessment_problems.all()),
                "earned_points": 0.0,
                "percentage": 0.0,
                "passing_percentage": float(assessment.passing_percentage),
                "is_passed": False,
            }

        assessment_problems = assessment.assessment_problems.select_related("problem").all()
        total_possible_points = sum(ap.points for ap in assessment_problems)
        total_problems_count = assessment_problems.count()

        problem_scores = {}
        problem_statuses = {}

        # Fetch all submissions by this student for this assessment
        submissions = CodeSubmission.objects.filter(
            assessment=assessment,
            student=student,
        ).order_by("submitted_at")

        for sub in submissions:
            pid = sub.problem_id
            if pid not in problem_scores or sub.score > problem_scores[pid]:
                problem_scores[pid] = float(sub.score)
                problem_statuses[pid] = sub.status

        # Calculate achieved points
        earned_points = 0.0
        solved_count = 0

        for ap in assessment_problems:
            pid = ap.problem_id
            pct = problem_scores.get(pid, 0.0)
            earned = (pct / 100.0) * ap.points
            earned_points += earned
            if problem_statuses.get(pid) == STATUS_ACCEPTED:
                solved_count += 1

        overall_percentage = (
            round((earned_points / total_possible_points) * 100.0, 2)
            if total_possible_points > 0
            else 0.0
        )
        is_passed = overall_percentage >= float(assessment.passing_percentage)

        # Update or record AssessmentAttempt
        AssessmentAttempt.objects.update_or_create(
            student=student,
            assessment=assessment,
            defaults={
                "score": overall_percentage,
                "is_passed": is_passed,
                "is_completed": len(problem_scores) == total_problems_count,
            },
        )

        return {
            "assessment_id": assessment.id,
            "student_id": student.student_id,
            "student_name": f"{student.first_name} {student.last_name or ''}".strip(),
            "title": assessment.title,
            "total_problems": total_problems_count,
            "problems_attempted": len(problem_scores),
            "problems_solved": solved_count,
            "total_possible_points": total_possible_points,
            "earned_points": round(earned_points, 2),
            "percentage": overall_percentage,
            "passing_percentage": float(assessment.passing_percentage),
            "is_passed": is_passed,
        }
