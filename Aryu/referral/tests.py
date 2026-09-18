from django.test import TestCase
from django.contrib.auth.hashers import check_password
from rest_framework.test import APIClient
from rest_framework import status
from .models import Referral


class ReferralModelAndAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_referral_creation_and_autogeneration(self):
        ref1 = Referral.objects.create(
            name="Alice",
            email="alice@example.com",
            password="plainPassword123",
            status="active",
        )
        self.assertEqual(ref1.coupon_code, "PASSATS001")
        self.assertEqual(ref1.url, "www.passats.aryuacademy.com/PASSATS001")
        self.assertTrue(ref1.password.startswith("pbkdf2_sha256$"))
        self.assertTrue(ref1.check_password("plainPassword123"))

        ref2 = Referral.objects.create(
            name="Bob",
            email="bob@example.com",
            password="anotherPassword456",
            status="inactive",
        )
        self.assertEqual(ref2.coupon_code, "PASSATS002")
        self.assertEqual(ref2.url, "www.passats.aryuacademy.com/PASSATS002")
        self.assertEqual(ref2.status, "inactive")

    def test_referral_api_crud(self):
        # 1. POST (Create)
        create_payload = {
            "name": "Charlie",
            "email": "charlie@example.com",
            "password": "Password789!",
            "status": "active",
        }
        res_create = self.client.post("/api/referral/", create_payload, format="json")
        self.assertEqual(res_create.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res_create.data["success"])
        ref_id = res_create.data["data"]["id"]
        self.assertEqual(res_create.data["data"]["coupon_code"], "PASSATS001")
        self.assertEqual(res_create.data["data"]["url"], "www.passats.aryuacademy.com/PASSATS001")

        # Verify hashed in DB
        db_ref = Referral.objects.get(id=ref_id)
        self.assertTrue(check_password("Password789!", db_ref.password))

        # 2. GET (List)
        res_list = self.client.get("/api/referral/")
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        self.assertTrue(res_list.data["success"])
        self.assertEqual(len(res_list.data["data"]), 1)

        # 3. GET (Retrieve detail)
        res_detail = self.client.get(f"/api/referral/{ref_id}/")
        self.assertEqual(res_detail.status_code, status.HTTP_200_OK)
        self.assertEqual(res_detail.data["data"]["email"], "charlie@example.com")

        # 4. PATCH (Partial update)
        patch_payload = {
            "name": "Charlie Updated",
            "status": "inactive",
        }
        res_patch = self.client.patch(f"/api/referral/{ref_id}/", patch_payload, format="json")
        self.assertEqual(res_patch.status_code, status.HTTP_200_OK)
        self.assertEqual(res_patch.data["data"]["name"], "Charlie Updated")
        self.assertEqual(res_patch.data["data"]["status"], "inactive")

        # Verify password wasn't wiped
        db_ref.refresh_from_db()
        self.assertTrue(check_password("Password789!", db_ref.password))

        # 5. PUT (Full update including password change)
        put_payload = {
            "name": "Charlie Full Update",
            "email": "charlie_updated@example.com",
            "password": "NewSecretPassword123!",
            "status": "active",
        }
        res_put = self.client.put(f"/api/referral/{ref_id}/", put_payload, format="json")
        self.assertEqual(res_put.status_code, status.HTTP_200_OK)
        self.assertEqual(res_put.data["data"]["name"], "Charlie Full Update")
        db_ref.refresh_from_db()
        self.assertTrue(check_password("NewSecretPassword123!", db_ref.password))

        # 6. DELETE
        res_del = self.client.delete(f"/api/referral/{ref_id}/")
        self.assertEqual(res_del.status_code, status.HTTP_200_OK)
        self.assertFalse(Referral.objects.filter(id=ref_id).exists())

    def test_coupon_sequence_progression(self):
        r1 = Referral.objects.create(name="U1", email="u1@test.com", password="pwd")
        r2 = Referral.objects.create(name="U2", email="u2@test.com", password="pwd")
        r3 = Referral.objects.create(name="U3", email="u3@test.com", password="pwd")

        self.assertEqual(r1.coupon_code, "PASSATS001")
        self.assertEqual(r2.coupon_code, "PASSATS002")
        self.assertEqual(r3.coupon_code, "PASSATS003")

        self.assertEqual(r1.url, "www.passats.aryuacademy.com/PASSATS001")
        self.assertEqual(r2.url, "www.passats.aryuacademy.com/PASSATS002")
        self.assertEqual(r3.url, "www.passats.aryuacademy.com/PASSATS003")

    def test_filter_and_validation(self):
        Referral.objects.create(name="Active User", email="active@test.com", password="pwd", status="active")
        Referral.objects.create(name="Inactive User", email="inactive@test.com", password="pwd", status="inactive")

        # Filter by active
        res_active = self.client.get("/api/referral/?status=active")
        self.assertEqual(res_active.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res_active.data["data"]), 1)
        self.assertEqual(res_active.data["data"][0]["status"], "active")

        # Validation error for invalid status
        res_invalid = self.client.post("/api/referral/", {
            "name": "Bad User",
            "email": "bad@test.com",
            "status": "not_valid",
        }, format="json")
        self.assertEqual(res_invalid.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(res_invalid.data["success"])

    def test_generate_coupon_and_url_api(self):
        # 1. Preview code before storing in database
        payload = {
            "name": "Frontend User",
            "email": "frontend@test.com",
            "password": "Password123!",
        }
        res_generate = self.client.post("/api/referral/generate", payload, format="json")
        self.assertEqual(res_generate.status_code, status.HTTP_200_OK)
        self.assertTrue(res_generate.data["success"])
        self.assertEqual(res_generate.data["data"]["coupon_code"], "PASSATS001")
        self.assertEqual(res_generate.data["data"]["url"], "www.passats.aryuacademy.com/PASSATS001")
        self.assertEqual(res_generate.data["data"]["name"], "Frontend User")
        self.assertEqual(res_generate.data["data"]["email"], "frontend@test.com")

        # Verify nothing was saved in database yet
        self.assertEqual(Referral.objects.count(), 0)

        # 2. Also works via GET
        res_get = self.client.get("/api/referral/generate?name=Frontend+User&email=frontend@test.com")
        self.assertEqual(res_get.status_code, status.HTTP_200_OK)
        self.assertEqual(res_get.data["data"]["coupon_code"], "PASSATS001")

        # 3. Now frontend submits form with the generated coupon and url
        submit_payload = {
            "name": "Frontend User",
            "email": "frontend@test.com",
            "password": "Password123!",
            "coupon_code": res_generate.data["data"]["coupon_code"],
            "url": res_generate.data["data"]["url"],
            "status": "active",
        }
        res_submit = self.client.post("/api/referral/", submit_payload, format="json")
        self.assertEqual(res_submit.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Referral.objects.count(), 1)
        created_ref = Referral.objects.first()
        self.assertEqual(created_ref.coupon_code, "PASSATS001")

        # 4. Next call to generate should now give PASSATS002
        res_next = self.client.post("/api/referral/generate", {"email": "another@test.com"}, format="json")
        self.assertEqual(res_next.data["data"]["coupon_code"], "PASSATS002")
        self.assertEqual(res_next.data["data"]["url"], "www.passats.aryuacademy.com/PASSATS002")

        # 5. Calling generate with already existing email returns error
        res_dup_email = self.client.post("/api/referral/generate", {"email": "frontend@test.com"}, format="json")
        self.assertEqual(res_dup_email.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(res_dup_email.data["success"])


