import logging
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from courses.models import Course
from webinar.models import Webinar

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Webinar)
def auto_sync_course_from_webinar(sender, instance, created, **kwargs):
    """
    Listens for Webinar/Bootcamp changes.
    - type == False (Bootcamp): Automatically creates/updates ONE Course record with status='Active'.
    - type == True (Webinar): Skips Course generation completely.
    """
    # Only sync if it is a Bootcamp (type == False) and not deleted
    if instance.is_deleted or getattr(instance, "type", True) is not False:
        return

    def _sync_course():
        try:
            notes_identifier = f"Auto-created from Webinar/Bootcamp ID: {instance.id}"
            new_fee = instance.price if instance.price is not None else (instance.regular_price or 0)

            # Determine course status: reads instance status if available, defaulting to "Active"
            raw_status = getattr(instance, "status", "Active")
            if isinstance(raw_status, bool):
                course_status = "Active" if raw_status else "Inactive"
            else:
                course_status = str(raw_status).capitalize() if raw_status else "Active"

            with transaction.atomic():
                # update_or_create prevents duplicates and updates the Course status to Active
                course, was_created = Course.objects.update_or_create(
                    notes=notes_identifier,
                    is_archived=False,
                    defaults={
                        "course_name": instance.title,
                        "status": course_status,  # Ensured to be "Active" or mapped status
                        "fee": new_fee,
                        "created_by": str(getattr(instance, "created_by", "system")),
                        "created_by_type": str(getattr(instance, "created_by_type", "super_admin")),
                    }
                )
                action = "Auto-created" if was_created else "Updated"
                logger.info(
                    f"[SUCCESS] {action} Course '{course.course_name}' "
                    f"(ID: {course.id}) with status '{course_status}' for Bootcamp ID {instance.id}"
                )

        except Exception as e:
            logger.error(
                f"[ERROR] Failed to sync Course for Bootcamp ID {instance.id}: {str(e)}", 
                exc_info=True
            )

    transaction.on_commit(_sync_course)