"""
whatsapp/validators.py

Campaign state-machine validators.

Centralizes the transition rules referenced by CampaignCancelView,
CampaignDeleteView, and CampaignDuplicateView so the rules live in exactly
one place rather than being re-implemented (and risking drift) inside each
view. Raises rest_framework.exceptions.ValidationError directly so views
can call these as guard clauses without their own try/except boilerplate.
"""

from rest_framework.exceptions import ValidationError

from .models import WhatsAppCampaign

# States from which a campaign can be cancelled.
# A campaign that's already terminal (completed/failed/cancelled) or still
# a draft (nothing to cancel) is excluded.
CANCELLABLE_STATES = {
    WhatsAppCampaign.STATUS_QUEUED,
    WhatsAppCampaign.STATUS_RUNNING,
    WhatsAppCampaign.STATUS_PAUSED,
}

# States from which a campaign may be hard-deleted.
# Anything actively queued/running must be cancelled first — deleting a
# RUNNING campaign would orphan in-flight Celery tasks referencing its rows.
DELETABLE_STATES = {
    WhatsAppCampaign.STATUS_DRAFT,
    WhatsAppCampaign.STATUS_COMPLETED,
    WhatsAppCampaign.STATUS_FAILED,
    WhatsAppCampaign.STATUS_CANCELLED,
}


def validate_cancellable(campaign: WhatsAppCampaign) -> None:
    """
    Raise ValidationError unless `campaign.status` permits cancellation.
    Called by CampaignCancelView before any state mutation.
    """
    if campaign.status not in CANCELLABLE_STATES:
        raise ValidationError(
            {
                "error": (
                    f"Campaign is '{campaign.status}' and cannot be cancelled. "
                    f"Only campaigns in {sorted(CANCELLABLE_STATES)} are cancellable."
                )
            }
        )


def validate_deletable(campaign: WhatsAppCampaign) -> None:
    """
    Raise ValidationError unless `campaign.status` permits hard deletion.
    Called by CampaignDeleteView before any DB mutation.
    """
    if campaign.status not in DELETABLE_STATES:
        raise ValidationError(
            {
                "error": (
                    f"Campaign is '{campaign.status}' and cannot be deleted. "
                    f"Cancel the campaign first, or wait for it to reach a "
                    f"terminal state ({sorted(DELETABLE_STATES)})."
                )
            }
        )


def validate_owner_or_staff(campaign: WhatsAppCampaign, user) -> None:
    """
    Raise ValidationError unless `user` created the campaign or is staff.

    Applied to mutating endpoints (cancel/delete/duplicate) so any
    authenticated user cannot tamper with campaigns they don't own.
    Read endpoints (list/detail/analytics) remain visible to all
    authenticated users — ownership is enforced only on writes, matching
    the existing TriggerBroadcastView which similarly gates only on
    IsAuthenticated for reads but tracks created_by for audit on writes.
    """
    if user.is_staff:
        return
    if campaign.created_by_id is not None and campaign.created_by_id != user.id:
        raise ValidationError(
            {"error": "You do not have permission to modify this campaign."}
        )
    