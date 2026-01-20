# live_quiz/common/utils.py
def get_actor_from_request(request):
    user = request.user

    if not user or not getattr(user, "is_authenticated", False):
        return "system"

    return getattr(user, "username", "unknown")
