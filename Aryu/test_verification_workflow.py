import os
import sys
import django

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Aryu.settings")
django.setup()

from django.test import Client
from resume.models import ResumeRegistration

def run_tests():
    print("=== STARTING EMAIL VERIFICATION WORKFLOW TEST ===")
    client = Client()

    # Step 1: Register a new user
    email = "test_verify_user_123@example.com"
    ResumeRegistration.objects.filter(email=email).delete()

    reg_data = {
        "first_name": "Test",
        "last_name": "User",
        "email": email,
        "phone": "9876543210",
        "password": "Password@123",
        "city": "TestCity",
        "state": "TestState",
        "country": "TestCountry",
        "turnstileToken": "test_pass"
    }

    print("\n1. Submitting registration request to /api/register/...")
    response = client.post("/api/register/", data=reg_data, content_type="application/json")
    print(f"Response status: {response.status_code}")
    print(f"Response data: {response.json()}")
    assert response.status_code == 201, f"Expected 201, got {response.status_code}"

    # Verify user in database
    user = ResumeRegistration.objects.filter(email=email).first()
    assert user is not None, "User should exist in database"
    assert user.is_verified is False, f"Expected is_verified=False, got {user.is_verified}"
    print("  [SUCCESS] User created in database with is_verified=False.")

    # Step 2: Check list endpoint excludes unverified user
    print("\n2. Checking list endpoints for unverified user...")
    list_resp = client.get("/api/resume-registration/")
    print(f"List response status: {list_resp.status_code}")
    list_data = list_resp.json()
    
    # Handle list or paginated response
    results = list_data.get("results", list_data) if isinstance(list_data, dict) else list_data
    unverified_found = any(u.get("id") == user.id or u.get("email") == email for u in results)
    assert not unverified_found, "Unverified user MUST NOT appear in list endpoint results!"
    print("  [SUCCESS] Unverified user excluded from /api/resume-registration/ list endpoint.")

    # Check detail endpoint returns 404
    detail_resp = client.get(f"/api/resume-registration/{user.id}/")
    assert detail_resp.status_code == 404, f"Expected 404 for unverified user retrieve, got {detail_resp.status_code}"
    print("  [SUCCESS] Unverified user detail endpoint returned 404 Not Found.")

    # Step 3: Check email verification token and expiry in DB
    print("\n3. Verifying email token generation & storage in DB...")
    token = user.email_verification_token
    expiry = user.email_verification_token_expiry
    print(f"Token: {token}")
    print(f"Expiry: {expiry}")
    assert token is not None and len(token) > 0, "email_verification_token must be non-empty"
    assert expiry is not None, "email_verification_token_expiry must be set"
    print("  [SUCCESS] Verification token and expiry correctly stored in database.")

    # Step 4: Trigger verification endpoint with token
    print("\n4. Triggering verification endpoint with generated token...")
    verify_resp = client.get(f"/api/verify-email/?token={token}")
    print(f"Verify response status: {verify_resp.status_code}")
    print(f"Verify response data: {verify_resp.json()}")
    assert verify_resp.status_code == 200, f"Expected 200, got {verify_resp.status_code}"

    # Refresh user from DB
    user.refresh_from_db()
    assert user.is_verified is True, "User is_verified should now be True"
    assert user.email_verification_token is None, "Token should be invalidated (set to None)"
    print("  [SUCCESS] User is_verified updated to True and token invalidated.")

    # Step 5: Query list endpoint again for verified user
    print("\n5. Querying list endpoint for now-verified user...")
    list_resp_2 = client.get("/api/resume-registration/")
    list_data_2 = list_resp_2.json()
    results_2 = list_data_2.get("results", list_data_2) if isinstance(list_data_2, dict) else list_data_2
    verified_found = any(u.get("id") == user.id or u.get("email") == email for u in results_2)
    assert verified_found, "Verified user MUST appear in list endpoint results!"
    print("  [SUCCESS] Verified user now appears in list endpoint response.")

    # Check detail endpoint returns 200 OK for verified user
    detail_resp_2 = client.get(f"/api/resume-registration/{user.id}/")
    assert detail_resp_2.status_code == 200, f"Expected 200 for verified user detail, got {detail_resp_2.status_code}"
    print("  [SUCCESS] Verified user detail endpoint returned 200 OK.")

    # Step 6: Attempt to use the same verification token twice
    print("\n6. Attempting to reuse the same verification token...")
    reuse_resp = client.get(f"/api/verify-email/?token={token}")
    print(f"Token reuse response status: {reuse_resp.status_code}")
    print(f"Token reuse response data: {reuse_resp.json()}")
    assert reuse_resp.status_code == 400, f"Expected 400, got {reuse_resp.status_code}"
    print("  [SUCCESS] Reusing token was rejected with 400 Bad Request.")

    # Cleanup
    user.delete()
    print("\n=== ALL 6 TESTING CHECKLIST STEPS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    run_tests()
