from django.db import transaction

from lead.whatsapp.models import MessageTemplate
from lead.whatsapp.services.meta_client import MetaClient


class TemplateSyncService:

    STATUS_MAP = {
        "APPROVED": MessageTemplate.Status.APPROVED,
        "PENDING": MessageTemplate.Status.PENDING,
        "REJECTED": MessageTemplate.Status.REJECTED,
    }

    @classmethod
    def sync_templates(cls):

        client = MetaClient()

        response = client.list_templates()

        meta_templates = response.get("data", [])

        local_templates = {
            t.meta_template_name: t
            for t in MessageTemplate.objects.all()
        }

        templates_to_update = []

        for remote in meta_templates:

            local = local_templates.get(remote["name"])

            if not local:
                continue

            local.status = cls.STATUS_MAP.get(
                remote["status"],
                MessageTemplate.Status.PENDING,
            )

            local.category = remote.get(
                "category",
                local.category,
            )

            local.language = remote.get(
                "language",
                local.language,
            )

            local.meta_id = remote.get(
                "id",
                local.meta_id,
            )

            templates_to_update.append(local)

        if templates_to_update:

            MessageTemplate.objects.bulk_update(
                templates_to_update,
                [
                    "status",
                    "category",
                    "language",
                    "meta_id",
                ]
            )

        return len(templates_to_update)
    
