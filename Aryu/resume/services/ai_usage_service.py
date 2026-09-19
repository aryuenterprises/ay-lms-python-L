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
    Supports individual Gemini generation tracking and aggregated user reporting.
    """

    @staticmethod
    def _format_generation(log: AIUsageLog) -> Dict[str, Any]:
        """Format an AIUsageLog model instance into a standardized generation dictionary."""
        return {
            "operation": log.operation,
            "provider": log.provider,
            "model": log.model,
            "input_tokens": log.input_tokens,
            "output_tokens": log.output_tokens,
            "total_tokens": log.total_tokens,
            "cached_tokens": log.cached_tokens,
            "latency_ms": log.latency_ms,
            "request_id": str(log.request_id) if log.request_id else None,
        }

    @staticmethod
    def log_usage(
        user: Optional[Union[ResumeRegistration, int]] = None,
        operation: str = "general",
        usage_data: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
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
    ) -> Optional[Union[AIUsageLog, List[AIUsageLog]]]:
        """
        Persist an AIUsageLog record immediately.
        If usage_data is a list of dicts, iterates and creates one AIUsageLog per generation.
        Extracts usage details either from usage_data dictionary (from FastAPI)
        or direct parameters.

        Guaranteed not to raise exceptions to prevent disrupting critical client flows.
        """
        try:
            # If usage_data is a list of generation objects, delegate to log_usages
            if isinstance(usage_data, list):
                return AIUsageService.log_usages(
                    user=user,
                    default_operation=operation,
                    usage_data=usage_data,
                    default_request_id=request_id,
                    default_status=status,
                )

            # 1. Resolve user
            user_obj = None
            if isinstance(user, ResumeRegistration):
                user_obj = user
            elif isinstance(user, int):
                user_obj = ResumeRegistration.objects.filter(id=user).first()
            elif hasattr(user, "id") and getattr(user, "is_authenticated", False):
                user_obj = ResumeRegistration.objects.filter(id=user.id).first()

            # 2. Extract and merge usage values
            usage_dict = usage_data if isinstance(usage_data, dict) else {}

            resolved_operation = usage_dict.get("operation") or operation or "general"
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

            resolved_status = usage_dict.get("status") or status or "success"

            # 4. Create log record
            log_entry = AIUsageLog.objects.create(
                user=user_obj,
                operation=resolved_operation,
                provider=resolved_provider,
                model=resolved_model,
                request_id=resolved_request_id,
                input_tokens=resolved_input_tokens,
                output_tokens=resolved_output_tokens,
                total_tokens=resolved_total_tokens,
                cached_tokens=resolved_cached_tokens,
                latency_ms=resolved_latency,
                status=resolved_status,
                error_message=str(error_message or ""),
                metadata=metadata if isinstance(metadata, dict) else {},
            )
            return log_entry

        except Exception as exc:
            logger.error(f"Failed to persist AIUsageLog: {exc}", exc_info=True)
            return None

    @staticmethod
    def log_usages(
        user: Optional[Union[ResumeRegistration, int]] = None,
        default_operation: str = "general",
        usage_data: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = None,
        default_request_id: Optional[Union[uuid.UUID, str]] = None,
        default_status: str = "success",
    ) -> List[AIUsageLog]:
        """
        Log multiple Gemini generation usage records (or a single record).
        Iterates through the complete usage_data list and creates one AIUsageLog
        record per Gemini generation without aggregating.
        """
        if not usage_data:
            return []

        items = usage_data if isinstance(usage_data, list) else [usage_data]
        created_logs = []

        for item in items:
            if not isinstance(item, dict):
                continue
            op = item.get("operation") or default_operation
            req_id = item.get("request_id") or default_request_id
            st = item.get("status") or default_status
            log_record = AIUsageService.log_usage(
                user=user,
                operation=op,
                usage_data=item,
                status=st,
                request_id=req_id,
            )
            if log_record and isinstance(log_record, AIUsageLog):
                created_logs.append(log_record)

        return created_logs

    @staticmethod
    def get_user_token_usage(user_or_id: Optional[Union[ResumeRegistration, int]]) -> Dict[str, Any]:
        """
        Calculate token usage and retrieve all individual generations for a single user from AIUsageLog.
        Returns empty generations list and zero totals if no usage records exist.
        """
        default_usage = {
            "generations": [],
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_tokens": 0,
            "total_cached_tokens": 0,
            "generation_count": 0,
            # Backward-compatible aliases
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_tokens": 0,
        }

        if not user_or_id:
            return default_usage

        user_id = user_or_id.id if hasattr(user_or_id, "id") else user_or_id

        try:
            logs = list(AIUsageLog.objects.filter(user_id=user_id).order_by("id"))
            if not logs:
                return default_usage

            generations = []
            total_input = 0
            total_output = 0
            total_tokens = 0
            total_cached = 0

            for log in logs:
                generations.append(AIUsageService._format_generation(log))
                total_input += log.input_tokens or 0
                total_output += log.output_tokens or 0
                total_tokens += log.total_tokens or 0
                total_cached += log.cached_tokens or 0

            gen_count = len(generations)

            return {
                "generations": generations,
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_tokens": total_tokens,
                "total_cached_tokens": total_cached,
                "generation_count": gen_count,
                # Backward-compatible aliases
                "input_tokens": total_input,
                "output_tokens": total_output,
                "cached_tokens": total_cached,
            }
        except Exception as exc:
            logger.error(f"Error calculating token usage for user {user_id}: {exc}", exc_info=True)
            return default_usage

    @staticmethod
    def get_users_token_usage_batch(user_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """
        Efficiently calculate token usage and retrieve individual generations for multiple users
        in a single database query (prevents N+1).
        """
        if not user_ids:
            return {}

        def create_default():
            return {
                "generations": [],
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "total_cached_tokens": 0,
                "generation_count": 0,
                # Backward-compatible aliases
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_tokens": 0,
            }

        usage_map = {uid: create_default() for uid in user_ids}

        try:
            logs = AIUsageLog.objects.filter(user_id__in=user_ids).order_by("id")
            for log in logs:
                uid = log.user_id
                if uid in usage_map:
                    entry = usage_map[uid]
                    entry["generations"].append(AIUsageService._format_generation(log))
                    entry["total_input_tokens"] += log.input_tokens or 0
                    entry["total_output_tokens"] += log.output_tokens or 0
                    entry["total_tokens"] += log.total_tokens or 0
                    entry["total_cached_tokens"] += log.cached_tokens or 0
                    entry["generation_count"] += 1

                    entry["input_tokens"] = entry["total_input_tokens"]
                    entry["output_tokens"] = entry["total_output_tokens"]
                    entry["cached_tokens"] = entry["total_cached_tokens"]

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
