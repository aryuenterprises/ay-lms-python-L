import logging
import uuid
from typing import Optional, Dict, Any, List, Union
from django.db import models
from django.utils import timezone
from datetime import timedelta
from ..models import AIUsageLog, ResumeRegistration

logger = logging.getLogger("resume")


class AIUsageService:
    """
    Centralized service for Gemini AI token accounting and analytics in Django.
    """

    @staticmethod
    def log_usage(
        user: Optional[Union[ResumeRegistration, int]] = None,
        operation: str = "general",
        usage_data: Optional[Dict[str, Any]] = None,
        status: str = "success",
        error_message: str = "",
        request_id: Optional[Union[uuid.UUID, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        latency_ms: Optional[int] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        cached_tokens: Optional[int] = None,
    ) -> Optional[AIUsageLog]:
        """
        Persist an AIUsageLog record immediately.
        Extracts usage details either from usage_data dictionary (from FastAPI)
        or direct parameters.

        Guaranteed not to raise exceptions to prevent disrupting critical client flows.
        """
        try:
            # 1. Resolve user
            user_obj = None
            if isinstance(user, ResumeRegistration):
                user_obj = user
            elif isinstance(user, int):
                user_obj = ResumeRegistration.objects.filter(id=user).first()
            elif hasattr(user, "id") and user.is_authenticated:
                user_obj = ResumeRegistration.objects.filter(id=user.id).first()

            # 2. Extract and merge usage values
            usage_dict = usage_data if isinstance(usage_data, dict) else {}

            resolved_provider = usage_dict.get("provider") or provider or "gemini"
            resolved_model = usage_dict.get("model") or model or "unknown"
            
            resolved_input_tokens = int(usage_dict.get("input_tokens") or input_tokens or 0)
            resolved_output_tokens = int(usage_dict.get("output_tokens") or output_tokens or 0)
            
            # If total_tokens is not provided, sum input and output tokens
            calculated_total = resolved_input_tokens + resolved_output_tokens
            resolved_total_tokens = int(
                usage_dict.get("total_tokens")
                if usage_dict.get("total_tokens") is not None
                else (total_tokens if total_tokens is not None else calculated_total)
            )
            
            resolved_cached_tokens = int(usage_dict.get("cached_tokens") or cached_tokens or 0)

            resolved_latency = (
                usage_dict.get("latency_ms")
                if usage_dict.get("latency_ms") is not None
                else latency_ms
            )
            if resolved_latency is not None:
                try:
                    resolved_latency = int(resolved_latency)
                except (ValueError, TypeError):
                    resolved_latency = None

            # 3. Request ID handling
            raw_req_id = usage_dict.get("request_id") or request_id
            resolved_request_id = None
            if raw_req_id:
                try:
                    if isinstance(raw_req_id, uuid.UUID):
                        resolved_request_id = raw_req_id
                    else:
                        resolved_request_id = uuid.UUID(str(raw_req_id))
                except (ValueError, AttributeError):
                    resolved_request_id = None

            # 4. Create log record
            log_entry = AIUsageLog.objects.create(
                user=user_obj,
                operation=operation,
                provider=resolved_provider,
                model=resolved_model,
                request_id=resolved_request_id,
                input_tokens=resolved_input_tokens,
                output_tokens=resolved_output_tokens,
                total_tokens=resolved_total_tokens,
                cached_tokens=resolved_cached_tokens,
                latency_ms=resolved_latency,
                status=status,
                error_message=str(error_message or ""),
                metadata=metadata if isinstance(metadata, dict) else {},
            )
            return log_entry

        except Exception as exc:
            logger.error(f"Failed to persist AIUsageLog: {exc}", exc_info=True)
            return None

    @staticmethod
    def get_user_token_usage(user_or_id: Optional[Union[ResumeRegistration, int]]) -> Dict[str, int]:
        """
        Calculate aggregated token usage for a single user from AIUsageLog.
        Returns zeros if no usage records exist.
        """
        default_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "generations": 0,
        }

        if not user_or_id:
            return default_usage

        user_id = user_or_id.id if hasattr(user_or_id, "id") else user_or_id

        try:
            agg = AIUsageLog.objects.filter(user_id=user_id).aggregate(
                input_tokens=models.Sum("input_tokens"),
                output_tokens=models.Sum("output_tokens"),
                total_tokens=models.Sum("total_tokens"),
                cached_tokens=models.Sum("cached_tokens"),
                generations=models.Count("id"),
            )

            return {
                "input_tokens": agg.get("input_tokens") or 0,
                "output_tokens": agg.get("output_tokens") or 0,
                "total_tokens": agg.get("total_tokens") or 0,
                "cached_tokens": agg.get("cached_tokens") or 0,
                "generations": agg.get("generations") or 0,
            }
        except Exception as exc:
            logger.error(f"Error calculating token usage for user {user_id}: {exc}", exc_info=True)
            return default_usage

    @staticmethod
    def get_users_token_usage_batch(user_ids: List[int]) -> Dict[int, Dict[str, int]]:
        """
        Efficiently calculate token usage for multiple users in a single query (prevents N+1).
        """
        if not user_ids:
            return {}

        default_item = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "generations": 0,
        }

        usage_map = {uid: dict(default_item) for uid in user_ids}

        try:
            results = (
                AIUsageLog.objects.filter(user_id__in=user_ids)
                .values("user_id")
                .annotate(
                    input_tokens=models.Sum("input_tokens"),
                    output_tokens=models.Sum("output_tokens"),
                    total_tokens=models.Sum("total_tokens"),
                    cached_tokens=models.Sum("cached_tokens"),
                    generations=models.Count("id"),
                )
            )

            for r in results:
                uid = r["user_id"]
                if uid in usage_map:
                    usage_map[uid] = {
                        "input_tokens": r.get("input_tokens") or 0,
                        "output_tokens": r.get("output_tokens") or 0,
                        "total_tokens": r.get("total_tokens") or 0,
                        "cached_tokens": r.get("cached_tokens") or 0,
                        "generations": r.get("generations") or 0,
                    }
        except Exception as exc:
            logger.error(f"Error calculating batch token usage: {exc}", exc_info=True)

        return usage_map

    @staticmethod
    def get_analytics_summary(
        period: Optional[str] = None,
        user_id: Optional[int] = None,
        operation: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get aggregated analytics for overall, today, this_week, this_month.
        """
        qs = AIUsageLog.objects.all()

        if user_id:
            qs = qs.filter(user_id=user_id)
        if operation:
            qs = qs.filter(operation=operation)
        if model:
            qs = qs.filter(model=model)

        now = timezone.now()

        if period == "today":
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            qs = qs.filter(created_at__gte=start_of_day)
        elif period == "this_week":
            # Monday of current week
            start_of_week = (now - timedelta(days=now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            qs = qs.filter(created_at__gte=start_of_week)
        elif period == "this_month":
            start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            qs = qs.filter(created_at__gte=start_of_month)

        agg = qs.aggregate(
            input_tokens=models.Sum("input_tokens"),
            output_tokens=models.Sum("output_tokens"),
            total_tokens=models.Sum("total_tokens"),
            cached_tokens=models.Sum("cached_tokens"),
            generations=models.Count("id"),
            avg_latency_ms=models.Avg("latency_ms"),
        )

        return {
            "period": period or "overall",
            "input_tokens": agg.get("input_tokens") or 0,
            "output_tokens": agg.get("output_tokens") or 0,
            "total_tokens": agg.get("total_tokens") or 0,
            "cached_tokens": agg.get("cached_tokens") or 0,
            "generations": agg.get("generations") or 0,
            "avg_latency_ms": round(agg.get("avg_latency_ms") or 0, 2),
        }
