from rest_framework.renderers import JSONRenderer


class SimpleMessageRenderer(JSONRenderer):
    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = renderer_context["response"]
        request = renderer_context.get("request")
        view = renderer_context.get("view")

        # ❌ ERROR RESPONSE
        if response.status_code >= 400:
            return super().render({
                "success": False,
                "message": self._get_error_message(data)
            }, accepted_media_type, renderer_context)

        # ✅ DELETE
        if request and request.method == "DELETE":
            return super().render({
                "success": True,
                "message": "Deleted successfully"
            }, accepted_media_type, renderer_context)

        # ✅ ALL OTHER CASES
        return super().render({
            "success": True,
            "message": self._get_success_message(request, view),
            "data": data
        }, accepted_media_type, renderer_context)

    def _get_success_message(self, request, view):
        if not request:
            return "Success"

        # 🔹 CUSTOM ACTION
        if hasattr(view, "action") and view.action not in [
            "list", "retrieve", "create", "update", "partial_update", "destroy"
        ]:
            return getattr(view, "success_message_action", "Action completed successfully")

        # 🔹 CREATE
        if request.method == "POST" and hasattr(view, "success_message_create"):
            return view.success_message_create

        # 🔹 UPDATE
        if request.method in ["PUT", "PATCH"] and hasattr(view, "success_message_update"):
            return view.success_message_update

        # 🔹 DEFAULT
        if request.method == "POST":
            return "Created successfully"
        if request.method in ["PUT", "PATCH"]:
            return "Updated successfully"

        return "Success"

    def _get_error_message(self, data):
        if isinstance(data, dict):
            for value in data.values():
                if isinstance(value, list):
                    return value[0]
                if isinstance(value, str):
                    return value
        return "Something went wrong"


