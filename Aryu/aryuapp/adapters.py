from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

class MyAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        # Block creation of User accounts
        return False


class MySocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        """
        DO NOT create User model
        DO NOT connect social account to user
        ALLOW social login to proceed so we can fetch email
        """
        return
