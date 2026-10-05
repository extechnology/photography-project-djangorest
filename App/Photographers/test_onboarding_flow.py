from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from App.Auth.auth_models import User, PasswordlessLoginOTP
from App.Photographers.photo_models import PhotographerProfile
from rest_framework_simplejwt.tokens import RefreshToken


class PhotographerOnboardingFlowTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_registration_otp_verify_contract_new_user(self):
        email = "sarang_new@example.com"
        otp_code = "123456"
        PasswordlessLoginOTP.objects.create(email=email, otp=otp_code)

        url = reverse('registration-otp-verify')
        response = self.client.post(url, {
            "email": email,
            "otp": otp_code
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["message"], "OTP verified successfully")
        self.assertTrue(data["is_new_user"])

        user_data = data["user"]
        self.assertEqual(user_data["email"], email)
        self.assertEqual(user_data["fullname"], "")
        self.assertEqual(user_data["phone"], "")
        self.assertEqual(user_data["occupation"], "")
        self.assertIsNone(user_data["avatar_url"])
        self.assertFalse(user_data["is_onboarded"])
        self.assertEqual(user_data["role"], "photographer")
        self.assertTrue(user_data["is_email_verified"])

    def test_check_login_contract_onboarded_and_not_onboarded(self):
        user = User.objects.create_user(
            username="test_photographer",
            email="test_photographer@example.com",
            role=User.Role.PHOTOGRAPHER
        )
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        res = self.client.get(reverse('check-login'))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertTrue(data["is_logged_in"])
        self.assertFalse(data["user"]["is_onboarded"])
        self.assertEqual(data["user"]["fullname"], "")
        self.assertEqual(data["user"]["occupation"], "")

        # Now mark onboarded on profile
        profile, _ = PhotographerProfile.objects.get_or_create(user=user)
        profile.name = "Sarang Varma"
        profile.phone = "+919876543210"
        profile.occupation = "Wedding Photographer"
        profile.is_onboarded = True
        profile.save()
        user.fullname = "Sarang Varma"
        user.phone = "+919876543210"
        user.save()

        res2 = self.client.get(reverse('check-login'))
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        data2 = res2.json()
        self.assertTrue(data2["is_logged_in"])
        self.assertTrue(data2["user"]["is_onboarded"])
        self.assertEqual(data2["user"]["fullname"], "Sarang Varma")
        self.assertEqual(data2["user"]["phone"], "+919876543210")
        self.assertEqual(data2["user"]["occupation"], "Wedding Photographer")

    def test_get_onboarding_state(self):
        user = User.objects.create_user(
            username="onboard_tester",
            email="onboard_tester@example.com",
            role=User.Role.PHOTOGRAPHER
        )
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        url = reverse('photographer-onboarding')
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertFalse(data["is_onboarded"])
        self.assertEqual(data["onboarding_step"], 3)
        self.assertEqual(data["name"], "")
        self.assertEqual(data["phone"], "")
        self.assertEqual(data["occupation"], "")
        self.assertEqual(data["avatar_url"], "")

    def test_post_onboarding_validation_errors(self):
        user = User.objects.create_user(
            username="val_user",
            email="val_user@example.com",
            role=User.Role.PHOTOGRAPHER
        )
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        url = reverse('photographer-onboarding')

        # Missing name
        res = self.client.post(url, {
            "phone": "+15550199",
            "occupation": "Photographer"
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", res.json())

        # Missing phone
        res = self.client.post(url, {
            "name": "Sarang",
            "occupation": "Photographer"
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("phone", res.json())

        # Missing occupation
        res = self.client.post(url, {
            "name": "Sarang",
            "phone": "+15550199"
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("occupation", res.json())

    def test_post_onboarding_success_with_fullname_alias_and_url(self):
        user = User.objects.create_user(
            username="sarang_varma",
            email="sarang@example.com",
            role=User.Role.PHOTOGRAPHER
        )
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        url = reverse('photographer-onboarding')
        payload = {
            "fullname": "Sarang Varma",
            "phone": "+15550199",
            "occupation": "Wedding Photographer",
            "avatar_url": "https://cdn.exshare.io/avatars/photographer_15.jpg",
            "onboarding_step": 3
        }

        res = self.client.post(url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()

        self.assertEqual(data["status"], "success")
        self.assertEqual(data["message"], "Profile onboarding completed successfully")
        self.assertTrue(data["is_onboarded"])
        self.assertEqual(data["onboarding_step"], 3)

        # Profile assertions
        profile = data["profile"]
        self.assertEqual(profile["name"], "Sarang Varma")
        self.assertEqual(profile["phone"], "+15550199")
        self.assertEqual(profile["occupation"], "Wedding Photographer")
        self.assertEqual(profile["avatar_url"], "https://cdn.exshare.io/avatars/photographer_15.jpg")
        self.assertTrue(profile["is_onboarded"])
        self.assertEqual(profile["onboarding_step"], 3)
        self.assertEqual(profile["storage_used_bytes"], 0)

        # User assertions
        user_res = data["user"]
        self.assertEqual(user_res["id"], user.id)
        self.assertEqual(user_res["username"], "sarang_varma")
        self.assertEqual(user_res["email"], "sarang@example.com")
        self.assertEqual(user_res["fullname"], "Sarang Varma")
        self.assertEqual(user_res["phone"], "+15550199")
        self.assertEqual(user_res["avatar_url"], "https://cdn.exshare.io/avatars/photographer_15.jpg")
        self.assertTrue(user_res["is_onboarded"])

        # DB persistence check
        user.refresh_from_db()
        self.assertEqual(user.fullname, "Sarang Varma")
        self.assertEqual(user.phone, "+15550199")
        self.assertTrue(user.is_onboarded)

        profile_db = user.photographer_profile
        self.assertEqual(profile_db.name, "Sarang Varma")
        self.assertEqual(profile_db.phone, "+15550199")
        self.assertEqual(profile_db.occupation, "Wedding Photographer")
        self.assertTrue(profile_db.is_onboarded)
        self.assertEqual(profile_db.onboarding_step, 3)

    def test_patch_profiles_me_auto_onboard(self):
        user = User.objects.create_user(
            username="patch_user",
            email="patch_user@example.com",
            role=User.Role.PHOTOGRAPHER
        )
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        url = reverse('profile-me-patch')
        payload = {
            "fullname": "Sarang Varma",
            "phone": "+15550199",
            "occupation": "Wedding Photographer"
        }

        res = self.client.patch(url, payload, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        user.refresh_from_db()
        profile_db = user.photographer_profile
        self.assertTrue(profile_db.is_onboarded)
        self.assertEqual(profile_db.name, "Sarang Varma")
        self.assertEqual(profile_db.phone, "+15550199")
        self.assertEqual(profile_db.occupation, "Wedding Photographer")
        self.assertTrue(user.is_onboarded)

    def test_login_otp_verify_existing_onboarded_user(self):
        user = User.objects.create_user(
            username="sarang_existing",
            email="existing@example.com",
            role=User.Role.PHOTOGRAPHER,
            fullname="Sarang Varma",
            phone="+919876543210"
        )
        profile, _ = PhotographerProfile.objects.get_or_create(user=user)
        profile.name = "Sarang Varma"
        profile.phone = "+919876543210"
        profile.occupation = "Wildlife Photographer"
        profile.avatar_url = "https://cdn.exshare.io/avatars/user_42.jpg"
        profile.is_onboarded = True
        profile.save()

        otp_code = "654321"
        PasswordlessLoginOTP.objects.create(email=user.email, otp=otp_code)

        url = reverse('login-otp-verify')
        response = self.client.post(url, {
            "email": user.email,
            "otp": otp_code
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertFalse(data["is_new_user"])

        user_data = data["user"]
        self.assertEqual(user_data["id"], user.id)
        self.assertEqual(user_data["email"], user.email)
        self.assertEqual(user_data["fullname"], "Sarang Varma")
        self.assertEqual(user_data["phone"], "+919876543210")
        self.assertEqual(user_data["occupation"], "Wildlife Photographer")
        self.assertEqual(user_data["avatar_url"], "https://cdn.exshare.io/avatars/user_42.jpg")
        self.assertTrue(user_data["is_onboarded"])

    def test_post_onboarding_multipart_with_avatar_file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        import io
        from PIL import Image

        # Generate a small 10x10 RGB test image
        img_buffer = io.BytesIO()
        image = Image.new('RGB', (10, 10), color='blue')
        image.save(img_buffer, format='JPEG')
        img_content = img_buffer.getvalue()
        avatar_file = SimpleUploadedFile("avatar.jpg", img_content, content_type="image/jpeg")

        user = User.objects.create_user(
            username="avatar_user",
            email="avatar_user@example.com",
            role=User.Role.PHOTOGRAPHER
        )
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        url = reverse('onboarding-complete')
        res = self.client.post(url, {
            "name": "Avatar Photographer",
            "phone": "+1999888777",
            "occupation": "Portrait Photographer",
            "avatar": avatar_file,
            "onboarding_step": 3
        }, format='multipart')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["is_onboarded"])
        self.assertIn("avatar", data["profile"]["avatar_url"])
        self.assertTrue(data["profile"]["avatar_url"].endswith(".jpg"))
        self.assertEqual(data["user"]["fullname"], "Avatar Photographer")
        self.assertEqual(data["user"]["phone"], "+1999888777")

