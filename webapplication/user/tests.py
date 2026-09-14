import json
import re
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from django.contrib.auth.models import Group, Permission
from django.core import mail
from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone as dj_timezone
from google.cloud.exceptions import GoogleCloudError
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_403_FORBIDDEN, HTTP_201_CREATED, HTTP_204_NO_CONTENT, HTTP_404_NOT_FOUND, HTTP_409_CONFLICT, HTTP_500_INTERNAL_SERVER_ERROR
from rest_framework.test import APITestCase

import user.stone_device_views as stone_views
from devices.models import Camera
from user.models import StonesDetectionChunk, User, UploadMissions, EdgePrediction, EdgeCoverage
from user.upload_utils import get_upload_config
from user.utils import day_window


class UserBase(APITestCase):

    @staticmethod
    def add_users_special_permissions():
        delete_any_result_permission = Permission.objects.get(codename='delete_any_result')
        view_all_transactions_permission = Permission.objects.get(codename='view_all_transactions')

        staff_user = User.objects.get(id=1001)
        staff_user.user_permissions.add(delete_any_result_permission)
        staff_user.user_permissions.add(view_all_transactions_permission)
    
    @staticmethod
    def add_users_to_groups():
        group = Group.objects.get(name='Data_science_engineer')
        user = User.objects.get(id=1001)
        user.groups.add(group)

        group = Group.objects.get(name='Client')
        user = User.objects.get(id=1002)
        user.groups.add(group)
        user = User.objects.get(id=1003)
        user.groups.add(group)
        user = User.objects.get(id=1004)
        user.groups.add(group)
        user = User.objects.get(id=1005)
        user.groups.add(group)
        
    def setUp(self):
        self.add_users_to_groups()
        self.add_users_special_permissions()
        self.staff_user = User.objects.get(id=1001)
        self.ex_2_user = User.objects.get(id=1002)
        self.ex_3_user = User.objects.get(id=1003)
        self.all_results_user = User.objects.get(id=1004)
        self.all_results_no_acl_user = User.objects.get(id=1005)

class AuthTestCase(UserBase):
    fixtures = ("user/fixtures/user_fixtures.json",)

    def login_with_credentials(self, login_data):
        url = reverse("rest_login")
        return self.client.post(url, login_data)

    def test_user_login_with_username(self):
        login_data = {
            "username": "test_staff",
            "password": "AiL9uumi"
        }
        response = self.login_with_credentials(login_data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertTrue(response.data.get("key", False))

    def test_user_login_with_username_and_email(self):
        login_data = {
            "username": "test_staff",
            "e-mail": "test_staff@geoap.com",
            "password": "AiL9uumi"
        }
        response = self.login_with_credentials(login_data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertTrue(response.data.get("key", False))

    def test_user_logout_on_GET(self):
        self.client.force_login(self.ex_2_user)
        url = reverse("rest_logout")
        response_data = {'detail': 'Successfully logged out.'}
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data, response_data)

    def test_user_logout_on_POST(self):
        self.client.force_login(self.ex_2_user)
        url = reverse("rest_logout")
        response_data = {'detail': 'Successfully logged out.'}
        response = self.client.post(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data, response_data)

    def test_password_change(self):
        self.client.force_login(self.ex_2_user)
        new_password = "Ois@3ns1"
        input_data = {
          "new_password1": new_password,
          "new_password2": new_password
        }
        response_data = {'detail': 'New password has been saved.'}
        url = reverse("rest_password_change")
        response = self.client.post(url, input_data)

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data, response_data)

        login_data = {
            "username": self.ex_2_user.username,
            "password": new_password
        }
        response = self.login_with_credentials(login_data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertTrue(response.data.get("key", False))

    def test_reset_password(self):
        self.client.force_login(self.ex_3_user)
        input_data = {'email': self.ex_3_user.email}
        response_data = {'detail': 'Password reset e-mail has been sent.'}
        url = reverse("rest_password_reset")
        response = self.client.post(url, input_data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data, response_data)
        self.assertEqual(len(mail.outbox), 1)

    def test_get_current_user_details(self):
        self.client.force_login(self.staff_user)
        response_data = {
            'pk': 1001,
            'username': 'test_staff',
            'email': 'test_staff@geoap.com',
            'first_name': '',
            'last_name': '',
            'area_limit_ha': None,
            'planet_api_key': None,
            "balance": 100000,
            "on_hold": 0,
            "discount": 0,
            'trial_started_at': None,
            'trial_finished_at': None,
            'is_trial_end_notified': False,
            'receive_notification': True,
            'server_for_calculation_is_needed': False,
            'stone_google_folder': None,
            'country': 'US',
            'units_of_measurement': 'km',
            'timezone': 'America/Regina'
        }
        url = reverse("rest_user_details")
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data, response_data)

    def test_get_anonymous_user_details(self):
        response_data = {'detail': 'Authentication credentials were not provided.'}
        url = reverse("rest_user_details")
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)
        self.assertEqual(response.data, response_data)

    def test_current_user_partial_update(self):
        self.client.force_login(self.staff_user)
        input_data = {
            'username': 'admin',
            'email': 'admin_staff@geoap.com',
            'first_name': 'admin',
            'last_name': 'admin',
            'area_limit_ha': 100,
            'planet_api_key': "secret-api-key",
            'balance': 12345,
            'on_hold': 5,
            'discount': 100,
            'timezone': 'Europe/Kyiv'
        }
        response_data = {
            'pk': 1001,
            'username': 'admin',
            'email': 'test_staff@geoap.com',
            'first_name': 'admin',
            'last_name': 'admin',
            'area_limit_ha': None,
            'planet_api_key': "secret-api-key",
            'balance': 100000,
            'on_hold': 0,
            'discount': 0,
            'trial_started_at': None,
            'trial_finished_at': None,
            'is_trial_end_notified': False,
            'receive_notification': True,
            'stone_google_folder': None,
            'country': 'US',
            'units_of_measurement': 'km',
            'timezone': 'Europe/Kyiv'
        }
        url = reverse("rest_user_details")
        response = self.client.patch(url, input_data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data, response_data)

    def test_current_user_update(self):
        self.client.force_login(self.staff_user)
        input_data = {
            'username': 'admin',
            'email': 'admin_staff@geoap.com',
            'first_name': 'admin',
            'last_name': 'admin',
            'area_limit_ha': 100,
            'planet_api_key': "secret-api-key",
            'balance': 12345,
            'on_hold': 5,
            'discount': 100,
            'timezone': 'Europe/Kyiv'
        }
        response_data = {
            'pk': 1001,
            'username': 'admin',
            'email': 'test_staff@geoap.com',
            'first_name': 'admin',
            'last_name': 'admin',
            'area_limit_ha': None,
            'planet_api_key': "secret-api-key",
            'balance': 100000,
            'on_hold': 0,
            'discount': 0,
            'trial_started_at': None,
            'trial_finished_at': None,
            'is_trial_end_notified': False,
            'receive_notification': True,
            'stone_google_folder': None,
            'country': 'US',
            'units_of_measurement': 'km',
            'timezone': 'Europe/Kyiv'
        }
        url = reverse("rest_user_details")
        response = self.client.put(url, input_data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data, response_data)

    def test_current_user_update_invalid_timezone(self):
        self.client.force_login(self.staff_user)
        url = reverse("rest_user_details")
        response = self.client.patch(url, {'timezone': 'not/a-zone'})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertIn('timezone', response.data)
        self.staff_user.refresh_from_db()
        self.assertEqual(self.staff_user.timezone, 'America/Regina')

    def test_user_timezone_default(self):
        new_user = User.objects.create(username='timezone_default_user')
        self.assertEqual(new_user.timezone, 'America/Regina')

    def test_user_model_rejects_invalid_timezone(self):
        new_user = User(username='timezone_invalid_user', password='secret', timezone='not/a-zone')
        with self.assertRaises(DjangoValidationError) as context:
            new_user.full_clean()
        self.assertIn('timezone', context.exception.message_dict)

    def test_user_model_accepts_valid_timezone(self):
        new_user = User(username='timezone_valid_user', password='secret', timezone='Europe/Kyiv')
        new_user.full_clean()
        new_user.save()
        new_user.refresh_from_db()
        self.assertEqual(new_user.timezone, 'Europe/Kyiv')

    def test_user_signup_with_confirmation(self):
        username = "new_user"
        password = "TrmWe23kn"
        input_data = {
            "username": username,
            "email": "new_user@geoap.com",
            "password1": password,
            "password2": password
        }
        response_data = {'detail': 'Verification e-mail sent.'}
        url = reverse("rest_register")
        response = self.client.post(url, input_data)
        self.assertEqual(response.status_code, HTTP_201_CREATED)
        self.assertEqual(response.data, response_data)
        self.assertEqual(len(mail.outbox), 1)

        current_user = User.objects.get(username=input_data.get("username"), email=input_data.get("email"))
        self.assertEqual(len(current_user.groups.all()), 1)
        self.assertEqual(current_user.groups.first().name, "Client")
        
        url_matches = re.findall(r"http.*account-confirm-email.*\B", mail.outbox[0].body)
        self.assertTrue(url_matches)
        confirmation_url = url_matches[0]  # Confirmation URL built for FE purposes and doesn't contain "/api/" part
        url_parts = confirmation_url.split("signup")
        url_parts.insert(1, "api/signup")
        confirmation_url = "".join(url_parts)
        response_data = "Email has been successfully confirmed!"

        response = self.client.get(confirmation_url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data, response_data)

        response = self.login_with_credentials({
            "username": username,
            "password": password
        })
        self.assertEqual(response.status_code, HTTP_200_OK)

    def test_email_resend(self):
        username = "new_user_1"
        password = "TrmWe23kn"
        email = "new_user_1@geoap.com"
        input_data = {
            "username": username,
            "email": email,
            "password1": password,
            "password2": password
        }
        response_data = {'detail': 'Verification e-mail sent.'}
        url = reverse("rest_register")
        response = self.client.post(url, input_data)
        self.assertEqual(response.status_code, HTTP_201_CREATED)
        self.assertEqual(response.data, response_data)
        self.assertEqual(len(mail.outbox), 1)

        input_data = {"email": email}
        url = reverse("rest_resend_email")
        response = self.client.post(url, input_data)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 2)

    def test_user_login_with_wrong_password_fails(self):
        login_data = {
            "username": "test_staff",
            "password": "wrongpassword123"
        }
        response = self.login_with_credentials(login_data)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data.get("key", False))


class TransactionTestCase(UserBase):
    fixtures = (
        'user/fixtures/user_fixtures.json',
        'aoi/fixtures/aoi_fixtures.json',
        'aoi/fixtures/notebook_fixtures.json',
        'aoi/fixtures/request_fixtures.json',
        'user/fixtures/transaction_fixtures.json'
    )

    def test_get_transactions_list_authorized(self):
        expected_results = [
            {
                "id": 1002,
                "user": 1002,
                "amount": 30,
                "created_at": "2023-02-15T11:15:11.230000Z",
                "updated_at": "2023-02-15T11:15:11.230000Z",
                "request": None,
                "comment": "",
                "error": None,
                "completed": False,
                "rolled_back": False,
                "area_sq_km": None,
                "processed_area_sq_km": None
            }
        ]
        url = reverse("get_transactions_list")
        self.client.force_login(self.ex_2_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertIsNone(data["next"])
        self.assertIsNone(data["previous"])
        self.assertEqual(data["results"], expected_results)

    def test_get_transactions_list_authorized_as_admin(self):
        expected_results = [
            {
                "id": 1003,
                "user": 1003,
                "amount": -8.14,
                "created_at": "2023-02-15T11:16:21.210000Z",
                "updated_at": "2023-02-15T11:16:21.210000Z",
                "request": 1001,
                "comment": "",
                "error": None,
                "completed": True,
                "rolled_back": False,
                "area_sq_km": None,
                "processed_area_sq_km": None
            },
            {
                "id": 1002,
                "user": 1002,
                "amount": 30,
                "created_at": "2023-02-15T11:15:11.230000Z",
                "updated_at": "2023-02-15T11:15:11.230000Z",
                "request": None,
                "comment": "",
                "error": None,
                "completed": False,
                "rolled_back": False,
                "area_sq_km": None,
                "processed_area_sq_km": None
            },
            {
                "id": 1001,
                "user": 1001,
                "amount": -20.42,
                "created_at": "2023-02-15T11:14:31.140000Z",
                "updated_at": "2023-02-15T11:14:31.140000Z",
                "request": 1001,
                "comment": "",
                "error": None,
                "completed": True,
                "rolled_back": False,
                "area_sq_km": None,
                "processed_area_sq_km": None
            }
        ]
        url = reverse("get_transactions_list")
        self.client.force_login(self.staff_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 3)
        self.assertIsNone(data["next"])
        self.assertIsNone(data["previous"])
        self.assertEqual(data["results"], expected_results)

    def test_get_transactions_list_not_authorized(self):
        url = reverse("get_transactions_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    def test_post_transactions_not_allowed(self):
        self.client.force_login(self.ex_2_user)
        url = reverse("get_transactions_list")
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, 405)

    def test_get_transactions_list_month_year_filter(self):
        url = reverse("get_transactions_list")
        self.client.force_login(self.staff_user)
        response = self.client.get(url, {"month": 2, "year": 2023})
        self.assertEqual(response.status_code, HTTP_200_OK)
        data = response.json()
        # All 3 fixture transactions are in Feb 2023
        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["results"]), 3)

    def test_get_transactions_list_month_year_filter_no_match(self):
        url = reverse("get_transactions_list")
        self.client.force_login(self.staff_user)
        response = self.client.get(url, {"month": 1, "year": 2023})
        self.assertEqual(response.status_code, HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["results"], [])

    def test_get_transactions_list_month_filter_ignored_without_year(self):
        # Partial filter (only month, no year) should return all transactions
        url = reverse("get_transactions_list")
        self.client.force_login(self.staff_user)
        response = self.client.get(url, {"month": 2})
        self.assertEqual(response.status_code, HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 3)

    def test_get_transactions_list_pagination_page_size(self):
        url = reverse("get_transactions_list")
        self.client.force_login(self.staff_user)
        response = self.client.get(url, {"page_size": 2})
        self.assertEqual(response.status_code, HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["results"]), 2)
        self.assertIsNotNone(data["next"])
        self.assertIsNone(data["previous"])

    def test_get_transactions_list_pagination_second_page(self):
        url = reverse("get_transactions_list")
        self.client.force_login(self.staff_user)
        response = self.client.get(url, {"page_size": 2, "page": 2})
        self.assertEqual(response.status_code, HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["results"]), 1)
        self.assertIsNone(data["next"])
        self.assertIsNotNone(data["previous"])

    def test_transaction_serializer_processed_area_sq_km_null_when_no_request(self):
        url = reverse("get_transactions_list")
        self.client.force_login(self.ex_2_user)
        response = self.client.get(url)
        result = response.json()["results"][0]
        self.assertIn("processed_area_sq_km", result)
        self.assertIsNone(result["processed_area_sq_km"])


class UploadMissionsTestCase(UserBase):
    fixtures = (
        'user/fixtures/user_fixtures.json',
        'aoi/fixtures/notebook_fixtures.json',
    )

    def setUp(self):
        super().setUp()
        self.ex_2_user.stone_google_folder = 'test-bucket'
        self.ex_2_user.save(update_fields=['stone_google_folder'])

    # --- UploadMissionsListCreateAPIView ---

    def test_create_mission_authenticated(self):
        self.client.force_login(self.ex_2_user)
        url = reverse('upload_missions_list')
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, HTTP_201_CREATED)
        self.assertIn('id', response.data)
        self.assertIn('gcs_path', response.data)
        self.assertEqual(response.data['status'], UploadMissions.STATUS_IN_PROGRESS)
        # gcs_path format: YYYY/YYYY-MM-DD_HH-MM-SS
        gcs_path = response.data['gcs_path']
        parts = gcs_path.split('/')
        self.assertEqual(len(parts), 2)
        self.assertEqual(len(parts[0]), 4)  # year

    def test_create_mission_unauthenticated(self):
        url = reverse('upload_missions_list')
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    def test_list_missions_returns_only_own(self):
        # Create missions for two users
        self.client.force_login(self.ex_2_user)
        self.client.post(reverse('upload_missions_list'), {})
        self.client.post(reverse('upload_missions_list'), {})

        self.client.force_login(self.ex_3_user)
        self.client.post(reverse('upload_missions_list'), {})

        # ex_2_user sees only their 2 missions
        self.client.force_login(self.ex_2_user)
        response = self.client.get(reverse('upload_missions_list'))
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        for mission in response.data:
            self.assertEqual(mission['status'], UploadMissions.STATUS_IN_PROGRESS)

    def test_list_missions_unauthenticated(self):
        url = reverse('upload_missions_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    def test_create_mission_with_component(self):
        from aoi.models import Component
        component = Component.objects.get(pk=1001)
        self.client.force_login(self.ex_2_user)
        url = reverse('upload_missions_list')
        response = self.client.post(url, {'component': component.pk})
        self.assertEqual(response.status_code, HTTP_201_CREATED)
        self.assertEqual(response.data['component'], component.pk)
        self.assertEqual(response.data['component_name'], component.name)

    def test_create_mission_uses_default_upload_component(self):
        from aoi.models import Component
        component = Component.objects.get(pk=1001)
        self.ex_2_user.default_upload_component = component
        self.ex_2_user.save(update_fields=['default_upload_component'])

        self.client.force_login(self.ex_2_user)
        url = reverse('upload_missions_list')
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, HTTP_201_CREATED)
        self.assertEqual(response.data['component'], component.pk)

    # --- UploadMissionsUpdateAPIView ---

    def test_patch_mission_status_to_completed(self):
        self.client.force_login(self.ex_2_user)
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
        )
        url = reverse('upload_mission_detail', kwargs={'pk': mission.pk})
        response = self.client.patch(url, {'status': UploadMissions.STATUS_COMPLETED}, format='json')
        self.assertEqual(response.status_code, HTTP_200_OK)
        mission.refresh_from_db()
        self.assertEqual(mission.status, UploadMissions.STATUS_COMPLETED)

    def test_patch_mission_status_to_failed(self):
        self.client.force_login(self.ex_2_user)
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
        )
        url = reverse('upload_mission_detail', kwargs={'pk': mission.pk})
        response = self.client.patch(url, {'status': UploadMissions.STATUS_FAILED}, format='json')
        self.assertEqual(response.status_code, HTTP_200_OK)
        mission.refresh_from_db()
        self.assertEqual(mission.status, UploadMissions.STATUS_FAILED)

    def test_patch_mission_updates_uploaded_files(self):
        self.client.force_login(self.ex_2_user)
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
        )
        files = [{'name': 'video.mp4', 'type': 'data_video', 'size': 1024}]
        url = reverse('upload_mission_detail', kwargs={'pk': mission.pk})
        response = self.client.patch(url, {'status': UploadMissions.STATUS_COMPLETED, 'uploaded_files': files}, format='json')
        self.assertEqual(response.status_code, HTTP_200_OK)
        mission.refresh_from_db()
        self.assertEqual(mission.uploaded_files, files)

    def test_patch_mission_creates_trajectory_request_when_completed_with_component(self):
        from aoi.models import Component, Request
        component = Component.objects.get(pk=1001)
        self.ex_2_user.stone_google_folder = 'test-bucket'
        self.ex_2_user.save(update_fields=['stone_google_folder'])
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
            component=component,
        )
        self.client.force_login(self.ex_2_user)
        url = reverse('upload_mission_detail', kwargs={'pk': mission.pk})
        response = self.client.patch(url, {'status': UploadMissions.STATUS_COMPLETED}, format='json')
        self.assertEqual(response.status_code, HTTP_200_OK)
        mission.refresh_from_db()
        self.assertIsNotNone(mission.trajectory_request_id)
        req = Request.objects.get(pk=mission.trajectory_request_id)
        self.assertEqual(req.component, component)
        self.assertEqual(req.user, self.ex_2_user)
        self.assertIsNone(req.aoi)
        self.assertIsNone(req.polygon)
        expected_path = f"test-bucket/{self.ex_2_user.username}/2024/2024-01-01_10-00-00/"
        self.assertEqual(req.additional_parameter, expected_path)

    def test_patch_mission_no_trajectory_request_when_no_component(self):
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
            component=None,
        )
        self.client.force_login(self.ex_2_user)
        url = reverse('upload_mission_detail', kwargs={'pk': mission.pk})
        response = self.client.patch(url, {'status': UploadMissions.STATUS_COMPLETED}, format='json')
        self.assertEqual(response.status_code, HTTP_200_OK)
        mission.refresh_from_db()
        self.assertIsNone(mission.trajectory_request_id)

    def test_patch_mission_no_trajectory_request_when_already_exists(self):
        from aoi.models import Component, Request
        component = Component.objects.get(pk=1001)
        existing_request = Request.objects.create(
            user=self.ex_2_user,
            component=component,
        )
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
            component=component,
            trajectory_request=existing_request,
        )
        self.client.force_login(self.ex_2_user)
        url = reverse('upload_mission_detail', kwargs={'pk': mission.pk})
        response = self.client.patch(url, {'status': UploadMissions.STATUS_COMPLETED}, format='json')
        self.assertEqual(response.status_code, HTTP_200_OK)
        mission.refresh_from_db()
        # Should still be the original request, not a new one
        self.assertEqual(mission.trajectory_request_id, existing_request.pk)

    def test_patch_other_users_mission_returns_404(self):
        mission = UploadMissions.objects.create(
            user=self.ex_3_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
        )
        self.client.force_login(self.ex_2_user)
        url = reverse('upload_mission_detail', kwargs={'pk': mission.pk})
        response = self.client.patch(url, {'status': UploadMissions.STATUS_COMPLETED}, format='json')
        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)

    def test_mission_put_not_allowed(self):
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
        )
        self.client.force_login(self.ex_2_user)
        url = reverse('upload_mission_detail', kwargs={'pk': mission.pk})
        response = self.client.put(url, {'status': UploadMissions.STATUS_COMPLETED}, format='json')
        self.assertEqual(response.status_code, 405)

    def test_mission_serializer_trajectory_status_none_when_no_request(self):
        self.client.force_login(self.ex_2_user)
        self.client.post(reverse('upload_missions_list'), {})
        response = self.client.get(reverse('upload_missions_list'))
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertIsNone(response.data[0]['trajectory_status'])

    def test_mission_serializer_trajectory_status_when_request_exists(self):
        from aoi.models import Component, Request
        component = Component.objects.get(pk=1001)
        req = Request.objects.create(user=self.ex_2_user, component=component)
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_COMPLETED,
            component=component,
            trajectory_request=req,
        )
        self.client.force_login(self.ex_2_user)
        response = self.client.get(reverse('upload_missions_list'))
        self.assertEqual(response.status_code, HTTP_200_OK)
        traj = response.data[0]['trajectory_status']
        self.assertIsNotNone(traj)
        self.assertEqual(traj['id'], req.pk)
        self.assertFalse(traj['calculated'])
        self.assertFalse(traj['success'])
        self.assertIsNone(traj['error'])

    def test_patch_completed_mission_to_failed_without_trajectory_error_returns_400(self):
        self.client.force_login(self.ex_2_user)
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_COMPLETED,
        )
        url = reverse('upload_mission_detail', kwargs={'pk': mission.pk})
        response = self.client.patch(url, {'status': UploadMissions.STATUS_FAILED}, format='json')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        mission.refresh_from_db()
        self.assertEqual(mission.status, UploadMissions.STATUS_COMPLETED)

    def test_patch_completed_mission_to_failed_is_always_blocked(self):
        from aoi.models import Component, Request
        component = Component.objects.get(pk=1001)
        req = Request.objects.create(user=self.ex_2_user, component=component, error='Processing failed')
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_COMPLETED,
            component=component,
            trajectory_request=req,
        )
        self.client.force_login(self.ex_2_user)
        url = reverse('upload_mission_detail', kwargs={'pk': mission.pk})
        response = self.client.patch(url, {'status': UploadMissions.STATUS_FAILED}, format='json')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        mission.refresh_from_db()
        self.assertEqual(mission.status, UploadMissions.STATUS_COMPLETED)

    def test_trajectory_status_fields_exposed(self):
        from django.utils import timezone
        from aoi.models import Component, Request
        component = Component.objects.get(pk=1001)
        finished = timezone.now()
        req = Request.objects.create(
            user=self.ex_2_user, component=component,
            error='Something went wrong', finished_at=finished,
        )
        UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_COMPLETED,
            component=component,
            trajectory_request=req,
        )
        self.client.force_login(self.ex_2_user)
        response = self.client.get(reverse('upload_missions_list'))
        self.assertEqual(response.status_code, HTTP_200_OK)
        traj = response.data[0]['trajectory_status']
        self.assertEqual(traj['error'], 'Something went wrong')
        self.assertIsNotNone(traj['finished_at'])

    def test_rerun_trajectory_creates_new_request(self):
        from aoi.models import Component, Request
        component = Component.objects.get(pk=1001)
        self.ex_2_user.stone_google_folder = 'test-bucket'
        self.ex_2_user.save(update_fields=['stone_google_folder'])
        failed_req = Request.objects.create(
            user=self.ex_2_user, component=component, error='Processing failed'
        )
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_COMPLETED,
            component=component,
            trajectory_request=failed_req,
        )
        self.client.force_login(self.ex_2_user)
        url = reverse('upload_mission_rerun_trajectory', kwargs={'pk': mission.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        mission.refresh_from_db()
        self.assertNotEqual(mission.trajectory_request_id, failed_req.pk)
        new_req = Request.objects.get(pk=mission.trajectory_request_id)
        self.assertEqual(new_req.component, component)
        self.assertIsNone(new_req.error)

    def test_rerun_trajectory_blocked_when_not_failed(self):
        from aoi.models import Component, Request
        component = Component.objects.get(pk=1001)
        req = Request.objects.create(user=self.ex_2_user, component=component, success=True)
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_COMPLETED,
            component=component,
            trajectory_request=req,
        )
        self.client.force_login(self.ex_2_user)
        url = reverse('upload_mission_rerun_trajectory', kwargs={'pk': mission.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_rerun_trajectory_blocked_when_mission_not_completed(self):
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
        )
        self.client.force_login(self.ex_2_user)
        url = reverse('upload_mission_rerun_trajectory', kwargs={'pk': mission.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_patch_mission_unauthenticated_returns_403(self):
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
        )
        url = reverse('upload_mission_detail', kwargs={'pk': mission.pk})
        response = self.client.patch(url, {'status': UploadMissions.STATUS_COMPLETED}, format='json')
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    def test_patch_mission_invalid_status_returns_400(self):
        self.client.force_login(self.ex_2_user)
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
        )
        url = reverse('upload_mission_detail', kwargs={'pk': mission.pk})
        response = self.client.patch(url, {'status': 'not_a_valid_status'}, format='json')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_mission_serializer_component_name_null_when_no_component(self):
        UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
            component=None,
        )
        self.client.force_login(self.ex_2_user)
        response = self.client.get(reverse('upload_missions_list'))
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertIsNone(response.data[0]['component_name'])

    def test_list_missions_empty_when_none_exist(self):
        self.client.force_login(self.ex_2_user)
        response = self.client.get(reverse('upload_missions_list'))
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_error_field_in_response(self):
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_FAILED,
            error='data_video file name must match the format',
        )
        self.client.force_login(self.ex_2_user)
        response = self.client.get(reverse('upload_missions_list'))
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data[0]['error'], 'data_video file name must match the format')

    def test_patch_mission_with_error_field(self):
        self.client.force_login(self.ex_2_user)
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
        )
        url = reverse('upload_mission_detail', kwargs={'pk': mission.pk})
        response = self.client.patch(
            url,
            {'status': UploadMissions.STATUS_FAILED, 'error': 'Upload failed: HTTP 400'},
            format='json',
        )
        self.assertEqual(response.status_code, HTTP_200_OK)
        mission.refresh_from_db()
        self.assertEqual(mission.status, UploadMissions.STATUS_FAILED)
        self.assertEqual(mission.error, 'Upload failed: HTTP 400')

    def test_error_field_empty_by_default(self):
        self.client.force_login(self.ex_2_user)
        self.client.post(reverse('upload_missions_list'), {})
        response = self.client.get(reverse('upload_missions_list'))
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data[0]['error'], '')

    def test_signal_syncs_trajectory_error_to_mission(self):
        from aoi.models import Component, Request
        component = Component.objects.get(pk=1001)
        req = Request.objects.create(user=self.ex_2_user, component=component)
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_COMPLETED,
            component=component,
            trajectory_request=req,
        )
        req.error = 'Processing failed: out of memory'
        req.save(update_fields=['error'])
        mission.refresh_from_db()
        self.assertEqual(mission.error, 'Processing failed: out of memory')

    def test_signal_uses_fallback_message_when_no_error_text(self):
        from django.utils import timezone
        from aoi.models import Component, Request
        component = Component.objects.get(pk=1001)
        req = Request.objects.create(user=self.ex_2_user, component=component)
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_COMPLETED,
            component=component,
            trajectory_request=req,
        )
        req.finished_at = timezone.now()
        req.success = False
        req.save(update_fields=['finished_at', 'success'])
        mission.refresh_from_db()
        self.assertEqual(mission.error, 'Processing failed')

    def test_signal_does_not_sync_on_success(self):
        from aoi.models import Component, Request
        component = Component.objects.get(pk=1001)
        req = Request.objects.create(user=self.ex_2_user, component=component)
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_COMPLETED,
            component=component,
            trajectory_request=req,
        )
        req.success = True
        req.calculated = True
        req.save(update_fields=['success', 'calculated'])
        mission.refresh_from_db()
        self.assertEqual(mission.error, '')

    def test_signal_does_not_touch_unrelated_missions(self):
        from aoi.models import Component, Request
        component = Component.objects.get(pk=1001)
        req = Request.objects.create(user=self.ex_2_user, component=component)
        # Mission has no trajectory_request link
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
        )
        req.error = 'Processing failed'
        req.save(update_fields=['error'])
        mission.refresh_from_db()
        self.assertEqual(mission.error, '')


class GenerateUploadURLTestCase(UserBase):
    fixtures = ('user/fixtures/user_fixtures.json',)

    VALID_DATA_VIDEO_NAME = '00SAIRS_UNIT0120251028071253_0010.MP4'

    _DEFAULT_UPLOAD_CONFIG = {
        'unit_folder': 'unit',
        'upload': {
            'data_video': 'DCIM',
            'log': 'GPS_LOG',
            'calibration_video': None,
        }
    }

    def setUp(self):
        super().setUp()
        from aoi.models import Component
        component = Component.objects.create(
            name='Default Upload Component',
            image='test-image',
            upload_config=self._DEFAULT_UPLOAD_CONFIG,
        )
        self.ex_2_user.stone_google_folder = 'test-bucket'
        self.ex_2_user.default_upload_component = component
        self.ex_2_user.save(update_fields=['stone_google_folder', 'default_upload_component'])

    def _mock_gcs(self):
        mock_client = mock.MagicMock()
        mock_blob = mock.MagicMock()
        mock_blob.create_resumable_upload_session.return_value = 'https://storage.googleapis.com/resumable/session'
        mock_bucket = mock.MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_client.bucket.return_value = mock_bucket
        return mock_client, mock_blob, mock_bucket

    def test_missing_required_params_returns_400(self):
        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_missing_file_name_returns_400(self):
        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        response = self.client.get(url, {'file_type': 'video/mp4', 'upload_type': 'data_video'})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_invalid_upload_type_returns_400(self):
        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        response = self.client.get(url, {'file_name': 'test.mp4', 'file_type': 'video/mp4', 'upload_type': 'invalid_type'})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_unauthenticated_returns_403(self):
        url = reverse('generate_upload_url')
        response = self.client.get(url, {'file_name': 'test.mp4', 'file_type': 'video/mp4', 'upload_type': 'data_video'})
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    def test_invalid_data_video_filename_returns_400(self):
        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        bad_names = (
            'video.mp4',
            'random.MP4',
            'UNIT0120251028071253_0010.MP4',
            '00SAIRS_UNIT0120251028071253.MP4',
            # _IMP suffix — the real-world case that triggered this fix
            '00SAIRS_UNIT0120251028041252_0006_IMP.MP4',
        )
        for bad_name in bad_names:
            response = self.client.get(url, {'file_name': bad_name, 'file_type': 'video/mp4', 'upload_type': 'data_video'})
            self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST, msg=f"Expected 400 for filename: {bad_name}")
            self.assertIn('detail', response.data)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_generates_upload_url_for_data_video(self, mock_gcs_cls):
        mock_client, mock_blob, _ = self._mock_gcs()
        mock_gcs_cls.return_value = mock_client

        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        response = self.client.get(url, {'file_name': self.VALID_DATA_VIDEO_NAME, 'file_type': 'video/mp4', 'upload_type': 'data_video'})
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertIn('upload_url', response.data)
        self.assertIn('session_folder', response.data)
        self.assertEqual(response.data['upload_url'], 'https://storage.googleapis.com/resumable/session')

        # Verify blob path includes DCIM folder for data_video
        blob_path = mock_client.bucket.return_value.blob.call_args[0][0]
        self.assertIn('DCIM', blob_path)
        self.assertIn(self.VALID_DATA_VIDEO_NAME, blob_path)
        self.assertIn(self.ex_2_user.username, blob_path)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_generates_upload_url_for_log(self, mock_gcs_cls):
        mock_client, mock_blob, _ = self._mock_gcs()
        mock_gcs_cls.return_value = mock_client

        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        response = self.client.get(url, {'file_name': 'gps.log', 'file_type': 'text/plain', 'upload_type': 'log'})
        self.assertEqual(response.status_code, HTTP_200_OK)

        blob_path = mock_client.bucket.return_value.blob.call_args[0][0]
        self.assertIn('GPS_LOG', blob_path)
        self.assertIn('gps.log', blob_path)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_generates_upload_url_for_calibration_video(self, mock_gcs_cls):
        mock_client, mock_blob, _ = self._mock_gcs()
        mock_gcs_cls.return_value = mock_client

        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        response = self.client.get(url, {'file_name': 'calib.mp4', 'file_type': 'video/mp4', 'upload_type': 'calibration_video'})
        self.assertEqual(response.status_code, HTTP_200_OK)

        blob_path = mock_client.bucket.return_value.blob.call_args[0][0]
        # calibration_video has no subfolder and name is forced to 'calibration.<ext>'
        self.assertNotIn('DCIM', blob_path)
        self.assertNotIn('GPS_LOG', blob_path)
        self.assertIn('calibration.mp4', blob_path)
        self.assertNotIn('calib.mp4', blob_path)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_session_folder_reused_when_provided(self, mock_gcs_cls):
        mock_client, mock_blob, _ = self._mock_gcs()
        mock_gcs_cls.return_value = mock_client

        # Create a mission so the session_folder is found in DB
        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
        )

        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        response = self.client.get(url, {
            'file_name': self.VALID_DATA_VIDEO_NAME,
            'file_type': 'video/mp4',
            'upload_type': 'data_video',
            'session_folder': '2024/2024-01-01_10-00-00',
        })
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data['session_folder'], '2024/2024-01-01_10-00-00')

    def test_missing_file_type_returns_400(self):
        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        response = self.client.get(url, {'file_name': 'test.mp4', 'upload_type': 'data_video'})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_new_session_folder_format(self, mock_gcs_cls):
        mock_client, mock_blob, _ = self._mock_gcs()
        mock_gcs_cls.return_value = mock_client

        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        response = self.client.get(url, {'file_name': self.VALID_DATA_VIDEO_NAME, 'file_type': 'video/mp4', 'upload_type': 'data_video'})
        self.assertEqual(response.status_code, HTTP_200_OK)

        session_folder = response.data['session_folder']
        parts = session_folder.split('/')
        self.assertEqual(len(parts), 2)
        self.assertEqual(len(parts[0]), 4)  # YYYY
        self.assertRegex(parts[1], r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$')

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_blob_path_contains_unit_folder(self, mock_gcs_cls):
        mock_client, mock_blob, _ = self._mock_gcs()
        mock_gcs_cls.return_value = mock_client

        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        response = self.client.get(url, {'file_name': self.VALID_DATA_VIDEO_NAME, 'file_type': 'video/mp4', 'upload_type': 'data_video'})
        self.assertEqual(response.status_code, HTTP_200_OK)

        blob_path = mock_client.bucket.return_value.blob.call_args[0][0]
        # Default config has unit_folder = "unit"
        self.assertIn('/unit/', blob_path)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_session_folder_not_in_db_falls_back_to_default_component(self, mock_gcs_cls):
        from aoi.models import Component
        component = Component.objects.create(name='Test Component', image='test-image', upload_config=self._DEFAULT_UPLOAD_CONFIG)
        self.ex_2_user.default_upload_component = component
        self.ex_2_user.save(update_fields=['default_upload_component'])

        mock_client, mock_blob, _ = self._mock_gcs()
        mock_gcs_cls.return_value = mock_client

        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        # session_folder that doesn't exist in DB
        response = self.client.get(url, {
            'file_name': self.VALID_DATA_VIDEO_NAME,
            'file_type': 'video/mp4',
            'upload_type': 'data_video',
            'session_folder': '2099/2099-01-01_00-00-00',
        })
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data['session_folder'], '2099/2099-01-01_00-00-00')

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_gcs_exception_returns_400(self, mock_gcs_cls):
        mock_gcs_cls.side_effect = Exception("GCS error")
        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        response = self.client.get(url, {'file_name': self.VALID_DATA_VIDEO_NAME, 'file_type': 'video/mp4', 'upload_type': 'data_video'})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)

    def test_missing_upload_config_returns_400_not_500(self):
        """Regression: UnboundLocalError was raised when upload_config missing,
        turning a clean 400 into a 500. The _, ext = os.path.splitext() later
        in the same function shadowed the translation _ import."""
        from aoi.models import Component
        component = Component.objects.create(name='No Config Component', image='test-image')
        self.ex_2_user.default_upload_component = component
        self.ex_2_user.save(update_fields=['default_upload_component'])

        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        response = self.client.get(url, {
            'file_name': self.VALID_DATA_VIDEO_NAME,
            'file_type': 'video/mp4',
            'upload_type': 'data_video',
        })
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_duplicate_file_in_session_returns_409(self, mock_gcs_cls):
        mock_client, mock_blob, _ = self._mock_gcs()
        mock_gcs_cls.return_value = mock_client

        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
            uploaded_files=[{'name': self.VALID_DATA_VIDEO_NAME, 'type': 'data_video', 'size': 1024}],
        )

        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        response = self.client.get(url, {
            'file_name': self.VALID_DATA_VIDEO_NAME,
            'file_type': 'video/mp4',
            'upload_type': 'data_video',
            'session_folder': '2024/2024-01-01_10-00-00',
        })
        self.assertEqual(response.status_code, HTTP_409_CONFLICT)
        self.assertIn('already been uploaded', response.data['detail'])

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_calibration_video_name_forced_to_calibration(self, mock_gcs_cls):
        """Any calibration_video upload is stored as calibration.<ext> regardless of the original name."""
        mock_client, mock_blob, _ = self._mock_gcs()
        mock_gcs_cls.return_value = mock_client

        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        response = self.client.get(url, {
            'file_name': 'MY_CALIB_2024.MP4',
            'file_type': 'video/mp4',
            'upload_type': 'calibration_video',
        })
        self.assertEqual(response.status_code, HTTP_200_OK)
        blob_path = mock_client.bucket.return_value.blob.call_args[0][0]
        self.assertIn('calibration.MP4', blob_path)
        self.assertNotIn('MY_CALIB_2024', blob_path)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_duplicate_calibration_video_in_session_returns_409(self, mock_gcs_cls):
        """Second calibration upload to the same session is rejected (both renamed to calibration.<ext>)."""
        mock_client, mock_blob, _ = self._mock_gcs()
        mock_gcs_cls.return_value = mock_client

        mission = UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_IN_PROGRESS,
            uploaded_files=[{'name': 'calibration.mp4', 'type': 'calibration_video', 'size': 512}],
        )

        self.client.force_login(self.ex_2_user)
        url = reverse('generate_upload_url')
        response = self.client.get(url, {
            'file_name': 'other_calib.mp4',
            'file_type': 'video/mp4',
            'upload_type': 'calibration_video',
            'session_folder': '2024/2024-01-01_10-00-00',
        })
        self.assertEqual(response.status_code, HTTP_409_CONFLICT)


class GenerateDownloadURLTestCase(UserBase):
    fixtures = ('user/fixtures/user_fixtures.json',)

    _DEFAULT_UPLOAD_CONFIG = {
        'unit_folder': 'unit',
        'upload': {
            'data_video': 'DCIM',
            'log': 'GPS_LOG',
            'calibration_video': None,
        }
    }

    def setUp(self):
        super().setUp()
        from aoi.models import Component
        component = Component.objects.create(
            name='Default Upload Component',
            image='test-image',
            upload_config=self._DEFAULT_UPLOAD_CONFIG,
        )
        self.ex_2_user.stone_google_folder = 'test-bucket'
        self.ex_2_user.default_upload_component = component
        self.ex_2_user.save(update_fields=['stone_google_folder', 'default_upload_component'])

    def test_missing_params_returns_400(self):
        self.client.force_login(self.ex_2_user)
        url = reverse('generate_download_url')
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_missing_session_folder_returns_400(self):
        self.client.force_login(self.ex_2_user)
        url = reverse('generate_download_url')
        response = self.client.get(url, {'file_name': 'video.mp4', 'upload_type': 'data_video'})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_invalid_upload_type_returns_400(self):
        self.client.force_login(self.ex_2_user)
        url = reverse('generate_download_url')
        response = self.client.get(url, {
            'file_name': 'video.mp4',
            'upload_type': 'bad_type',
            'session_folder': '2024/2024-01-01_10-00-00',
        })
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_unauthenticated_returns_403(self):
        url = reverse('generate_download_url')
        response = self.client.get(url, {
            'file_name': 'video.mp4',
            'upload_type': 'data_video',
            'session_folder': '2024/2024-01-01_10-00-00',
        })
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_generates_download_url(self, mock_gcs_cls):
        mock_client = mock.MagicMock()
        mock_blob = mock.MagicMock()
        mock_blob.generate_signed_url.return_value = 'https://storage.googleapis.com/signed/download'
        mock_client.bucket.return_value.blob.return_value = mock_blob
        mock_gcs_cls.return_value = mock_client

        self.client.force_login(self.ex_2_user)
        url = reverse('generate_download_url')
        response = self.client.get(url, {
            'file_name': 'video.mp4',
            'upload_type': 'data_video',
            'session_folder': '2024/2024-01-01_10-00-00',
        })
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertIn('download_url', response.data)
        self.assertEqual(response.data['download_url'], 'https://storage.googleapis.com/signed/download')

        blob_path = mock_client.bucket.return_value.blob.call_args[0][0]
        self.assertIn('DCIM', blob_path)
        self.assertIn('video.mp4', blob_path)
        self.assertIn(self.ex_2_user.username, blob_path)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_download_url_blob_path_for_calibration(self, mock_gcs_cls):
        mock_client = mock.MagicMock()
        mock_blob = mock.MagicMock()
        mock_blob.generate_signed_url.return_value = 'https://storage.googleapis.com/signed/download'
        mock_client.bucket.return_value.blob.return_value = mock_blob
        mock_gcs_cls.return_value = mock_client

        self.client.force_login(self.ex_2_user)
        url = reverse('generate_download_url')
        response = self.client.get(url, {
            'file_name': 'calib.mp4',
            'upload_type': 'calibration_video',
            'session_folder': '2024/2024-01-01_10-00-00',
        })
        self.assertEqual(response.status_code, HTTP_200_OK)

        blob_path = mock_client.bucket.return_value.blob.call_args[0][0]
        self.assertNotIn('DCIM', blob_path)
        self.assertNotIn('GPS_LOG', blob_path)
        self.assertIn('calib.mp4', blob_path)

    def test_missing_file_name_returns_400(self):
        self.client.force_login(self.ex_2_user)
        url = reverse('generate_download_url')
        response = self.client.get(url, {
            'upload_type': 'data_video',
            'session_folder': '2024/2024-01-01_10-00-00',
        })
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_missing_upload_type_returns_400(self):
        self.client.force_login(self.ex_2_user)
        url = reverse('generate_download_url')
        response = self.client.get(url, {
            'file_name': 'video.mp4',
            'session_folder': '2024/2024-01-01_10-00-00',
        })
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_download_url_blob_path_for_log(self, mock_gcs_cls):
        mock_client = mock.MagicMock()
        mock_blob = mock.MagicMock()
        mock_blob.generate_signed_url.return_value = 'https://storage.googleapis.com/signed/download'
        mock_client.bucket.return_value.blob.return_value = mock_blob
        mock_gcs_cls.return_value = mock_client

        self.client.force_login(self.ex_2_user)
        url = reverse('generate_download_url')
        response = self.client.get(url, {
            'file_name': 'gps.log',
            'upload_type': 'log',
            'session_folder': '2024/2024-01-01_10-00-00',
        })
        self.assertEqual(response.status_code, HTTP_200_OK)

        blob_path = mock_client.bucket.return_value.blob.call_args[0][0]
        self.assertIn('GPS_LOG', blob_path)
        self.assertIn('gps.log', blob_path)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_gcs_exception_returns_400(self, mock_gcs_cls):
        mock_gcs_cls.side_effect = Exception("GCS error")
        self.client.force_login(self.ex_2_user)
        url = reverse('generate_download_url')
        response = self.client.get(url, {
            'file_name': 'video.mp4',
            'upload_type': 'data_video',
            'session_folder': '2024/2024-01-01_10-00-00',
        })
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)


class UploadConfigTestCase(APITestCase):

    def test_no_component_raises_error(self):
        with self.assertRaises(ValueError):
            get_upload_config()

    def test_none_component_raises_error(self):
        with self.assertRaises(ValueError):
            get_upload_config(None)

    def test_component_with_no_upload_config_raises_error(self):
        mock_component = mock.MagicMock()
        mock_component.upload_config = None
        with self.assertRaises(ValueError):
            get_upload_config(mock_component)

    def test_component_config_used(self):
        mock_component = mock.MagicMock()
        mock_component.upload_config = {
            'unit_folder': 'unit_1',
            'upload': {
                'data_video': 'DCIM',
                'log': 'GPS_LOG',
                'calibration_video': None,
            }
        }
        config = get_upload_config(mock_component)
        self.assertEqual(config['upload']['data_video'], 'DCIM')
        self.assertEqual(config['upload']['log'], 'GPS_LOG')
        self.assertIsNone(config['upload']['calibration_video'])

    def test_exclude_derived_from_upload_values(self):
        mock_component = mock.MagicMock()
        mock_component.upload_config = {
            'unit_folder': 'unit_1',
            'upload': {
                'data_video': 'DCIM',
                'log': 'GPS_LOG',
                'calibration_video': None,
            }
        }
        config = get_upload_config(mock_component)
        self.assertIn('DCIM', config['exclude'])
        self.assertIn('GPS_LOG', config['exclude'])
        self.assertNotIn(None, config['exclude'])


class GoogleBucketFolderAPIViewTestCase(UserBase):
    fixtures = ('user/fixtures/user_fixtures.json',)

    def setUp(self):
        super().setUp()
        self.ex_2_user.stone_google_folder = 'test-bucket'
        self.ex_2_user.save(update_fields=['stone_google_folder'])

    def _make_mock_blob(self, name):
        b = mock.MagicMock()
        b.name = name
        return b

    def _mock_gcs(self, blob_names):
        mock_client = mock.MagicMock()
        mock_bucket = mock.MagicMock()
        mock_bucket.exists.return_value = True
        mock_client.bucket.return_value = mock_bucket
        mock_client.list_blobs.return_value = [self._make_mock_blob(n) for n in blob_names]
        return mock_client

    def test_unauthenticated_returns_403(self):
        url = reverse('google_bucket_folder')
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    def test_no_stone_google_folder_returns_404(self):
        self.client.force_login(self.ex_3_user)
        url = reverse('google_bucket_folder')
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_bucket_not_found_returns_400(self, mock_gcs_cls):
        mock_client = mock.MagicMock()
        mock_bucket = mock.MagicMock()
        mock_bucket.exists.return_value = False
        mock_client.bucket.return_value = mock_bucket
        mock_gcs_cls.return_value = mock_client

        self.client.force_login(self.ex_2_user)
        url = reverse('google_bucket_folder')
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_empty_bucket_returns_204(self, mock_gcs_cls):
        mock_gcs_cls.return_value = self._mock_gcs([])
        self.client.force_login(self.ex_2_user)
        url = reverse('google_bucket_folder')
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_204_NO_CONTENT)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_returns_session_level_folders(self, mock_gcs_cls):
        username = self.ex_2_user.username
        blobs = [f'{username}/2024/2024-01-01_10-00-00/unit/DCIM/video.mp4']
        mock_gcs_cls.return_value = self._mock_gcs(blobs)

        self.client.force_login(self.ex_2_user)
        url = reverse('google_bucket_folder')
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertIn(f'{username}/2024/', response.data)
        self.assertIn(f'{username}/2024/2024-01-01_10-00-00/', response.data)
        # unit folder itself should not appear
        self.assertNotIn(f'{username}/2024/2024-01-01_10-00-00/unit/', response.data)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_excluded_folders_not_returned(self, mock_gcs_cls):
        username = self.ex_2_user.username
        blobs = [
            f'{username}/2024/session/unit/DCIM/video.mp4',
            f'{username}/2024/session/unit/GPS_LOG/gps.log',
        ]
        mock_gcs_cls.return_value = self._mock_gcs(blobs)

        self.client.force_login(self.ex_2_user)
        url = reverse('google_bucket_folder')
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        folders = response.data
        self.assertNotIn(f'{username}/2024/session/unit/', folders)
        self.assertNotIn(f'{username}/2024/session/unit/DCIM/', folders)
        self.assertNotIn(f'{username}/2024/session/unit/GPS_LOG/', folders)
        self.assertIn(f'{username}/2024/session/', folders)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_deduplicates_folders_across_blobs(self, mock_gcs_cls):
        username = self.ex_2_user.username
        blobs = [
            f'{username}/2024/session/unit/DCIM/video1.mp4',
            f'{username}/2024/session/unit/DCIM/video2.mp4',
        ]
        mock_gcs_cls.return_value = self._mock_gcs(blobs)

        self.client.force_login(self.ex_2_user)
        url = reverse('google_bucket_folder')
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        folders = response.data
        self.assertEqual(folders.count(f'{username}/2024/'), 1)
        self.assertEqual(folders.count(f'{username}/2024/session/'), 1)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_multiple_sessions_returned(self, mock_gcs_cls):
        username = self.ex_2_user.username
        blobs = [
            f'{username}/2024/2024-01-01_10-00-00/unit/DCIM/video.mp4',
            f'{username}/2024/2024-02-01_10-00-00/unit/DCIM/video.mp4',
        ]
        mock_gcs_cls.return_value = self._mock_gcs(blobs)

        self.client.force_login(self.ex_2_user)
        url = reverse('google_bucket_folder')
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        folders = response.data
        self.assertIn(f'{username}/2024/2024-01-01_10-00-00/', folders)
        self.assertIn(f'{username}/2024/2024-02-01_10-00-00/', folders)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_unit_variant_folder_names_not_returned(self, mock_gcs_cls):
        """unit_1, unit_test and other variants must not appear — only session-level folders"""
        username = self.ex_2_user.username
        blobs = [
            f'{username}/2024/2024-01-01_10-00-00/unit_1/DCIM/video.mp4',
            f'{username}/2024/2024-01-01_10-00-00/unit_test/GPS_LOG/gps.log',
        ]
        mock_gcs_cls.return_value = self._mock_gcs(blobs)

        self.client.force_login(self.ex_2_user)
        url = reverse('google_bucket_folder')
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_200_OK)
        folders = response.data
        self.assertIn(f'{username}/2024/2024-01-01_10-00-00/', folders)
        self.assertNotIn(f'{username}/2024/2024-01-01_10-00-00/unit_1/', folders)
        self.assertNotIn(f'{username}/2024/2024-01-01_10-00-00/unit_test/', folders)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_shallow_blobs_return_204(self, mock_gcs_cls):
        """Blobs only 2 parts deep (username/file.mp4) produce no folder entries"""
        username = self.ex_2_user.username
        blobs = [f'{username}/file.mp4']
        mock_gcs_cls.return_value = self._mock_gcs(blobs)

        self.client.force_login(self.ex_2_user)
        url = reverse('google_bucket_folder')
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_204_NO_CONTENT)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_gcs_exception_returns_400(self, mock_gcs_cls):
        mock_gcs_cls.side_effect = Exception("GCS error")
        self.client.force_login(self.ex_2_user)
        url = reverse('google_bucket_folder')
        response = self.client.get(url)
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)


VALID_PREDICTIONS_METADATA = {
    'uuid': 'test-uuid-1234',
    'version': '1',
    'gprmc': '$GPRMC,075513.00,A,5025.390269,N,03030.408529,E,0.0,98.2,100426,6.0,E,A,V*79',
    'model_name': 'stone_v1',
    'predictions': [{'x': 1, 'y': 2, 'confidence': 0.9}],
    'time_since_boot_sec': 123.45,
    'serial': 'CAM-001',
}

VALID_COVERAGE_METADATA = {
    'uuid': 'test-uuid-5678',
    'version': '1',
    'gprmc': '$GPRMC,075513.00,A,5025.390269,N,03030.408529,E,0.0,98.2,100426,6.0,E,A,V*79',
    'serial': 'CAM-001',
}

SMALL_JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 16


class StoneDeviceViewsBase(APITestCase):
    def setUp(self):
        stone_views._gcs_client_instance = None

        self.user = User.objects.create_user(
            username='camerauser',
            password='testpass',
            stones_storage_edge='test-bucket',
        )
        self.camera = Camera.objects.create(
            cam_serial_num='CAM-001',
            user=self.user,
        )

    def _mock_gcs(self):
        mock_client = mock.MagicMock()
        mock_bucket = mock.MagicMock()
        mock_client.bucket.return_value = mock_bucket
        return mock_client, mock_bucket

    def _metadata_file(self, data):
        return SimpleUploadedFile('meta.json', json.dumps(data).encode(), content_type='application/json')

    def _image_file(self, content=SMALL_JPEG):
        return SimpleUploadedFile('img.jpg', content, content_type='image/jpeg')


class PredictionsAPIViewTest(StoneDeviceViewsBase):

    def _post(self, data=None):
        return self.client.post(
            reverse('device_predictions'),
            data or {},
            format='multipart',
        )

    # --- auth ---

    def test_unknown_serial_returns_403(self):
        bad_meta = {**VALID_PREDICTIONS_METADATA, 'serial': 'UNKNOWN-CAM'}
        response = self._post({'metadata': self._metadata_file(bad_meta), 'image': self._image_file()})
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    # --- missing files ---

    def test_missing_both_files_returns_400(self):
        response = self._post()
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertIn('required', response.data['detail'])

    def test_missing_image_returns_400(self):
        response = self._post({'metadata': self._metadata_file(VALID_PREDICTIONS_METADATA)})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_missing_metadata_returns_400(self):
        response = self._post({'image': self._image_file()})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    # --- metadata validation ---

    def test_invalid_json_metadata_returns_400(self):
        bad_file = SimpleUploadedFile('meta.json', b'not json', content_type='application/json')
        response = self._post({'metadata': bad_file, 'image': self._image_file()})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertIn('metadata must be valid JSON', response.data['detail'])

    def test_missing_required_metadata_fields_returns_400(self):
        incomplete = {'uuid': 'abc', 'version': '1'}
        response = self._post({'metadata': self._metadata_file(incomplete), 'image': self._image_file()})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_invalid_field_type_returns_400(self):
        bad_data = {**VALID_PREDICTIONS_METADATA, 'time_since_boot_sec': 'not-a-number'}
        response = self._post({'metadata': self._metadata_file(bad_data), 'image': self._image_file()})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    # --- image size ---

    def test_image_too_large_returns_400(self):
        big_image = self._image_file(b'\xff' * (10 * 1024 * 1024 + 1))
        response = self._post({'metadata': self._metadata_file(VALID_PREDICTIONS_METADATA), 'image': big_image})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertIn('Image exceeds', response.data['detail'])

    @mock.patch('user.stone_device_views._gcs_client')
    def test_image_at_size_limit_is_accepted(self, mock_gcs_fn):
        mock_client, _ = self._mock_gcs()
        mock_gcs_fn.return_value = mock_client
        exact_image = self._image_file(b'\xff' * (10 * 1024 * 1024))
        response = self._post({'metadata': self._metadata_file(VALID_PREDICTIONS_METADATA), 'image': exact_image})
        self.assertEqual(response.status_code, HTTP_201_CREATED)

    # --- bucket not configured ---

    def test_no_bucket_configured_returns_400(self):
        self.user.stones_storage_edge = None
        self.user.save()
        response = self._post({'metadata': self._metadata_file(VALID_PREDICTIONS_METADATA), 'image': self._image_file()})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertIn('Storage bucket', response.data['detail'])

    # --- GCS upload ---

    @mock.patch('user.stone_device_views._gcs_client')
    def test_success_returns_201_with_uuid(self, mock_gcs_fn):
        mock_client, _ = self._mock_gcs()
        mock_gcs_fn.return_value = mock_client

        response = self._post({'metadata': self._metadata_file(VALID_PREDICTIONS_METADATA), 'image': self._image_file()})

        self.assertEqual(response.status_code, HTTP_201_CREATED)
        self.assertEqual(response.data['uuid'], VALID_PREDICTIONS_METADATA['uuid'])
        self.assertTrue(EdgePrediction.objects.filter(uuid=VALID_PREDICTIONS_METADATA['uuid']).exists())

    @mock.patch('user.stone_device_views._gcs_client')
    def test_success_uploads_jpg_and_json_to_gcs(self, mock_gcs_fn):
        mock_client, mock_bucket = self._mock_gcs()
        mock_gcs_fn.return_value = mock_client

        self._post({'metadata': self._metadata_file(VALID_PREDICTIONS_METADATA), 'image': self._image_file()})

        blob_paths = [call[0][0] for call in mock_bucket.blob.call_args_list]
        uuid = VALID_PREDICTIONS_METADATA['uuid']
        self.assertTrue(any(path.endswith(f'{uuid}.jpg') for path in blob_paths))
        self.assertTrue(any(path.endswith(f'{uuid}.json') for path in blob_paths))
        self.assertTrue(EdgePrediction.objects.filter(uuid=VALID_PREDICTIONS_METADATA['uuid']).exists())

    @mock.patch('user.stone_device_views._gcs_client')
    def test_success_creates_predictions_chunk_and_prediction_in_db(self, mock_gcs_fn):
        mock_client, _ = self._mock_gcs()
        mock_gcs_fn.return_value = mock_client

        self._post({'metadata': self._metadata_file(VALID_PREDICTIONS_METADATA), 'image': self._image_file()})

        self.assertTrue(
            StonesDetectionChunk.objects.filter(user=self.user, type=StonesDetectionChunk.TYPE_PREDICTIONS).exists()
        )

        prediction = EdgePrediction.objects.filter(uuid=VALID_PREDICTIONS_METADATA['uuid']).first()
        self.assertIsNotNone(prediction)
        self.assertEqual(prediction.serial, VALID_PREDICTIONS_METADATA['serial'])
        self.assertEqual(prediction.model_name, VALID_PREDICTIONS_METADATA['model_name'])
        self.assertTrue(prediction.image_path.endswith('.jpg'))
        self.assertEqual(prediction.captured_at, datetime(2026, 4, 10, 7, 55, 13, tzinfo=timezone.utc))
        self.assertEqual(prediction.speed, 0.0)

    @mock.patch('user.stone_device_views._gcs_client')
    def test_gcs_error_returns_500(self, mock_gcs_fn):
        mock_client = mock.MagicMock()
        mock_client.bucket.side_effect = GoogleCloudError('GCS down')
        mock_gcs_fn.return_value = mock_client

        response = self._post({'metadata': self._metadata_file(VALID_PREDICTIONS_METADATA), 'image': self._image_file()})

        self.assertEqual(response.status_code, HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn('Failed to store prediction', response.data['detail'])

    # --- NMEA & DB failure cases ---

    @mock.patch('user.stone_device_views._gcs_client')
    def test_void_gprmc_sets_location_captured_at_speed_to_none(self, mock_gcs_fn):
        mock_client, _ = self._mock_gcs()
        mock_gcs_fn.return_value = mock_client

        void_gprmc = '$GPRMC,123519,V,,,,,,,230394,,*33'
        meta = {**VALID_PREDICTIONS_METADATA, 'gprmc': void_gprmc}

        self._post(
            {'metadata': self._metadata_file(meta), 'image': self._image_file()}
        )

        prediction = EdgePrediction.objects.get(uuid=meta['uuid'])
        self.assertIsNone(prediction.location)
        self.assertIsNone(prediction.captured_at)
        self.assertIsNone(prediction.speed)

    @mock.patch('user.stone_device_views._gcs_client')
    def test_empty_coords_status_a_sets_location_captured_at_speed_to_none(self, mock_gcs_fn):
        """$GPRMC with status 'A' but missing lat/lon (Null Island) must set
        location, captured_at, and speed to None together, not only location."""
        mock_client, _ = self._mock_gcs()
        mock_gcs_fn.return_value = mock_client

        gprmc_no_coords = '$GPRMC,123519,A,,,,,,,230394,,*24'
        meta = {**VALID_PREDICTIONS_METADATA, 'gprmc': gprmc_no_coords}

        self._post({'metadata': self._metadata_file(meta), 'image': self._image_file()})

        prediction = EdgePrediction.objects.get(uuid=meta['uuid'])
        self.assertIsNone(prediction.location)
        self.assertIsNone(prediction.captured_at)
        self.assertIsNone(prediction.speed)

    @mock.patch('user.stone_device_views._gcs_client')
    def test_db_failure_returns_500(self, mock_gcs_fn):
        mock_client, _ = self._mock_gcs()
        mock_gcs_fn.return_value = mock_client

        with mock.patch.object(EdgePrediction.objects, 'create', side_effect=Exception('DB Error')):
            response = self._post({
                'metadata': self._metadata_file(VALID_PREDICTIONS_METADATA),
                'image': self._image_file(),
            })

        self.assertEqual(response.status_code, HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data['detail'], 'Failed to save prediction to database.')


class CoverageAPIViewTest(StoneDeviceViewsBase):

    def _post(self, data=None):
        return self.client.post(
            reverse('device_coverage'),
            data or {},
            format='multipart',
        )

    # --- auth ---

    def test_unknown_serial_returns_403(self):
        bad_meta = {**VALID_COVERAGE_METADATA, 'serial': 'UNKNOWN-CAM'}
        response = self._post({'metadata': self._metadata_file(bad_meta)})
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    # --- missing files ---

    def test_missing_both_files_returns_400(self):
        response = self._post()
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertIn('required', response.data['detail'])

    def test_missing_image_is_allowed(self):
        # metadata-only upload is valid; image is optional
        pass

    def test_missing_metadata_returns_400(self):
        response = self._post({'image': self._image_file()})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    # --- metadata validation ---

    def test_invalid_json_metadata_returns_400(self):
        bad_file = SimpleUploadedFile('meta.json', b'not json', content_type='application/json')
        response = self._post({'metadata': bad_file, 'image': self._image_file()})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertIn('metadata must be valid JSON', response.data['detail'])

    def test_missing_required_metadata_fields_returns_400(self):
        incomplete = {'uuid': 'abc'}
        response = self._post({'metadata': self._metadata_file(incomplete), 'image': self._image_file()})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    # --- image size ---

    def test_image_too_large_returns_400(self):
        big_image = self._image_file(b'\xff' * (10 * 1024 * 1024 + 1))
        response = self._post({'metadata': self._metadata_file(VALID_COVERAGE_METADATA), 'image': big_image})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertIn('Image exceeds', response.data['detail'])

    # --- bucket not configured ---

    def test_no_bucket_configured_returns_400(self):
        self.user.stones_storage_edge = None
        self.user.save()
        response = self._post({'metadata': self._metadata_file(VALID_COVERAGE_METADATA), 'image': self._image_file()})
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    # --- GCS upload ---

    @mock.patch('user.stone_device_views._gcs_client')
    def test_success_returns_201_with_uuid(self, mock_gcs_fn):
        mock_client, _ = self._mock_gcs()
        mock_gcs_fn.return_value = mock_client

        response = self._post({'metadata': self._metadata_file(VALID_COVERAGE_METADATA), 'image': self._image_file()})

        self.assertEqual(response.status_code, HTTP_201_CREATED)
        self.assertEqual(response.data['uuid'], VALID_COVERAGE_METADATA['uuid'])

        self.assertTrue(EdgeCoverage.objects.filter(uuid=VALID_COVERAGE_METADATA['uuid']).exists())

    @mock.patch('user.stone_device_views._gcs_client')
    def test_success_uploads_jpg_and_json_to_gcs(self, mock_gcs_fn):
        mock_client, mock_bucket = self._mock_gcs()
        mock_gcs_fn.return_value = mock_client

        self._post({'metadata': self._metadata_file(VALID_COVERAGE_METADATA), 'image': self._image_file()})

        blob_paths = [call[0][0] for call in mock_bucket.blob.call_args_list]
        uuid = VALID_COVERAGE_METADATA['uuid']
        self.assertTrue(any(path.endswith(f'{uuid}.jpg') for path in blob_paths))
        self.assertTrue(any(path.endswith(f'{uuid}.json') for path in blob_paths))
        self.assertTrue(EdgeCoverage.objects.filter(uuid=VALID_COVERAGE_METADATA['uuid']).exists())

    @mock.patch('user.stone_device_views._gcs_client')
    def test_success_creates_coverage_chunk_and_coverage_in_db(self, mock_gcs_fn):
        mock_client, _ = self._mock_gcs()
        mock_gcs_fn.return_value = mock_client

        self._post({'metadata': self._metadata_file(VALID_COVERAGE_METADATA), 'image': self._image_file()})

        self.assertTrue(
            StonesDetectionChunk.objects.filter(user=self.user, type=StonesDetectionChunk.TYPE_COVERAGE).exists()
        )
        coverage = EdgeCoverage.objects.filter(uuid=VALID_COVERAGE_METADATA['uuid']).first()
        self.assertIsNotNone(coverage)
        self.assertEqual(coverage.serial, VALID_COVERAGE_METADATA['serial'])
        self.assertTrue(coverage.image_path.endswith('.jpg'))
        self.assertEqual(coverage.captured_at, datetime(2026, 4, 10, 7, 55, 13, tzinfo=timezone.utc))
        self.assertEqual(coverage.speed, 0.0)

    @mock.patch('user.stone_device_views._gcs_client')
    def test_gcs_error_returns_500(self, mock_gcs_fn):
        mock_client = mock.MagicMock()
        mock_client.bucket.side_effect = GoogleCloudError('GCS down')
        mock_gcs_fn.return_value = mock_client

        response = self._post({'metadata': self._metadata_file(VALID_COVERAGE_METADATA), 'image': self._image_file()})

        self.assertEqual(response.status_code, HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn('Failed to store coverage', response.data['detail'])

    # --- metadata-only (no image) ---

    @mock.patch('user.stone_device_views._gcs_client')
    def test_metadata_only_returns_201(self, mock_gcs_fn):
        mock_client, _ = self._mock_gcs()
        mock_gcs_fn.return_value = mock_client

        response = self._post({'metadata': self._metadata_file(VALID_COVERAGE_METADATA)})

        self.assertEqual(response.status_code, HTTP_201_CREATED)
        self.assertEqual(response.data['uuid'], VALID_COVERAGE_METADATA['uuid'])

        coverage = EdgeCoverage.objects.get(uuid=VALID_COVERAGE_METADATA['uuid'])
        self.assertIsNone(coverage.image_path)

    @mock.patch('user.stone_device_views._gcs_client')
    def test_metadata_only_uploads_json_but_not_jpg(self, mock_gcs_fn):
        mock_client, mock_bucket = self._mock_gcs()
        mock_gcs_fn.return_value = mock_client

        self._post({'metadata': self._metadata_file(VALID_COVERAGE_METADATA)})

        blob_paths = [call[0][0] for call in mock_bucket.blob.call_args_list]
        uuid = VALID_COVERAGE_METADATA['uuid']
        self.assertTrue(any(path.endswith(f'{uuid}.json') for path in blob_paths))
        self.assertFalse(any(path.endswith(f'{uuid}.jpg') for path in blob_paths))

        coverage = EdgeCoverage.objects.filter(uuid=VALID_COVERAGE_METADATA['uuid']).first()
        self.assertIsNotNone(coverage)
        self.assertEqual(coverage.serial, VALID_COVERAGE_METADATA['serial'])
        self.assertIsNone(coverage.image_path)

    # --- NMEA & DB failure cases ---

    @mock.patch('user.stone_device_views._gcs_client')
    def test_void_gprmc_sets_location_captured_at_speed_to_none(self, mock_gcs_fn):
        mock_client, _ = self._mock_gcs()
        mock_gcs_fn.return_value = mock_client

        void_gprmc = '$GPRMC,123519,V,,,,,,,230394,,*33'
        meta = {**VALID_COVERAGE_METADATA, 'gprmc': void_gprmc}

        self._post({'metadata': self._metadata_file(meta)})

        coverage = EdgeCoverage.objects.get(uuid=meta['uuid'])
        self.assertIsNone(coverage.location)
        self.assertIsNone(coverage.captured_at)
        self.assertIsNone(coverage.speed)

    @mock.patch('user.stone_device_views._gcs_client')
    def test_empty_coords_status_a_sets_location_captured_at_speed_to_none(self, mock_gcs_fn):
        """$GPRMC with status 'A' but missing lat/lon (Null Island) must set
        location, captured_at, and speed to None together, not only location."""
        mock_client, _ = self._mock_gcs()
        mock_gcs_fn.return_value = mock_client

        gprmc_no_coords = '$GPRMC,123519,A,,,,,,,230394,,*24'
        meta = {**VALID_COVERAGE_METADATA, 'gprmc': gprmc_no_coords}

        self._post({'metadata': self._metadata_file(meta)})

        coverage = EdgeCoverage.objects.get(uuid=meta['uuid'])
        self.assertIsNone(coverage.location)
        self.assertIsNone(coverage.captured_at)
        self.assertIsNone(coverage.speed)

    @mock.patch('user.stone_device_views._gcs_client')
    def test_db_failure_returns_500(self, mock_gcs_fn):
        mock_client, _ = self._mock_gcs()
        mock_gcs_fn.return_value = mock_client

        with mock.patch.object(EdgeCoverage.objects, 'create', side_effect=Exception('DB Error')):
            response = self._post({
                'metadata': self._metadata_file(VALID_COVERAGE_METADATA),
                'image': self._image_file(),
            })

        self.assertEqual(response.status_code, HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data['detail'], 'Failed to save coverage to database.')


# ---------------------------------------------------------------------------
# parse_gprmc
# ---------------------------------------------------------------------------

class ParseGprmcTest(APITestCase):

    def test_valid_gprmc_populates_all_three_fields(self):
        fix = stone_views.parse_gprmc(VALID_PREDICTIONS_METADATA['gprmc'])
        self.assertIsNotNone(fix.location)
        self.assertEqual(fix.captured_at, datetime(2026, 4, 10, 7, 55, 13, tzinfo=timezone.utc))
        self.assertEqual(fix.speed, 0.0)

    def test_void_gprmc_returns_all_none(self):
        fix = stone_views.parse_gprmc('$GPRMC,123519,V,,,,,,,230394,,*33')
        self.assertIsNone(fix.location)
        self.assertIsNone(fix.captured_at)
        self.assertIsNone(fix.speed)

    def test_null_island_returns_all_none(self):
        """status 'A' with blank lat/lon must set all three fields to None,
        not only location. The fix is not valid, so captured_at and speed
        must not be trusted either."""
        fix = stone_views.parse_gprmc('$GPRMC,123519,A,,,,,,,230394,,*24')
        self.assertIsNone(fix.location)
        self.assertIsNone(fix.captured_at)
        self.assertIsNone(fix.speed)

    def test_empty_string_returns_all_none(self):
        fix = stone_views.parse_gprmc('')
        self.assertIsNone(fix.location)
        self.assertIsNone(fix.captured_at)
        self.assertIsNone(fix.speed)

    def test_unparseable_string_returns_all_none(self):
        fix = stone_views.parse_gprmc('not a gprmc string at all')
        self.assertIsNone(fix.location)
        self.assertIsNone(fix.captured_at)
        self.assertIsNone(fix.speed)

    def test_isolated_datetime_failure_keeps_location(self):
        """A bad date/time value must not remove a location that already
        parsed OK. The date/time try/except block must stay separate from
        the rest of the parser."""

        class _BadDatestampMsg:
            status = 'A'
            lat = '5025.390269'
            lon = '03030.408529'
            longitude = 50.42317115
            latitude = -30.50680881666667
            spd_over_grnd = 0.0

            @property
            def datestamp(self):
                raise ValueError('bad datestamp')

        with mock.patch('pynmea2.parse', return_value=_BadDatestampMsg()):
            fix = stone_views.parse_gprmc(VALID_PREDICTIONS_METADATA['gprmc'])

        self.assertIsNotNone(fix.location)
        self.assertIsNone(fix.captured_at)


class GcsClientSingletonTest(StoneDeviceViewsBase):

    @mock.patch('user.stone_device_views.storage')
    def test_client_instantiated_once(self, mock_storage):
        mock_storage.Client.from_service_account_json.return_value = mock.MagicMock()

        stone_views._gcs_client()
        stone_views._gcs_client()
        stone_views._gcs_client()


@override_settings(EDGE_ASSEMBLER_API_TOKEN='test-internal-token')
class EdgeChunkDataAPIViewTest(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='edgechunkuser',
            password='pass',
            stones_storage_edge='test-bucket',
        )
        self.predictions_chunk = StonesDetectionChunk.objects.create(
            user=self.user,
            date='2026-04-29',
            chunk=2,
            type=StonesDetectionChunk.TYPE_PREDICTIONS,
            gcs_path='edgechunkuser/2026-04-29/2/predictions/',
            processing_start_date='2026-04-29T12:00:00Z',
            status=StonesDetectionChunk.STATUS_PROCESSING,
        )
        self.coverage_chunk = StonesDetectionChunk.objects.create(
            user=self.user,
            date='2026-04-29',
            chunk=2,
            type=StonesDetectionChunk.TYPE_COVERAGE,
            gcs_path='edgechunkuser/2026-04-29/2/coverage/',
            processing_start_date='2026-04-29T12:00:00Z',
            status=StonesDetectionChunk.STATUS_PROCESSING,
        )
        self.prediction = EdgePrediction.objects.create(
            uuid='pred-uuid-1',
            chunk=self.predictions_chunk,
            serial='CAM-001',
            version='1',
            gprmc='$GPRMC,075513.00,A,5025.390269,N,03030.408529,E,0.0,98.2,100426,6.0,E,A,V*79',
            model_name='stone_v1',
            predictions=[{'xmin': 0.1, 'ymin': 0.1, 'xmax': 0.2, 'ymax': 0.2, 'confidence': 0.9}],
            image_path='edgechunkuser/2026-04-29/2/predictions/pred-uuid-1/pred-uuid-1.jpg',
        )
        self.coverage = EdgeCoverage.objects.create(
            uuid='cov-uuid-1',
            chunk=self.coverage_chunk,
            serial='CAM-001',
            version='1',
            gprmc='$GPRMC,075513.00,A,5025.390269,N,03030.408529,E,0.0,98.2,100426,6.0,E,A,V*79',
            image_path='edgechunkuser/2026-04-29/2/coverage/cov-uuid-1/cov-uuid-1.jpg',
        )

    def _get(self, token='test-internal-token', **params):
        query = {'username': 'edgechunkuser', 'date': '2026-04-29', 'chunk': '2'}
        query.update(params)
        headers = {'HTTP_X_INTERNAL_TOKEN': token} if token is not None else {}
        return self.client.get(reverse('edge_chunk_data'), query, **headers)

    def test_missing_token_returns_403(self):
        response = self._get(token=None)
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    def test_wrong_token_returns_403(self):
        response = self._get(token='not-the-right-token')
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    @override_settings(EDGE_ASSEMBLER_API_TOKEN='')
    def test_unconfigured_token_returns_403_even_with_matching_empty_token(self):
        response = self._get(token='')
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    def test_missing_query_params_returns_400(self):
        query = reverse('edge_chunk_data')
        response = self.client.get(
            query, {'username': 'edgechunkuser', 'date': '2026-04-29'},
            HTTP_X_INTERNAL_TOKEN='test-internal-token',
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_non_integer_chunk_returns_400_not_500(self):
        response = self._get(chunk='not-a-number')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_malformed_date_returns_400_not_500(self):
        response = self._get(date='not-a-date')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_returns_predictions_and_coverage_for_chunk(self):
        response = self._get()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(len(response.data['predictions']), 1)
        self.assertEqual(len(response.data['coverage']), 1)

        prediction_data = response.data['predictions'][0]
        self.assertEqual(prediction_data['serial'], 'CAM-001')
        self.assertEqual(prediction_data['image_path'], self.prediction.image_path)
        self.assertEqual(prediction_data['predictions'], self.prediction.predictions)

        coverage_data = response.data['coverage'][0]
        self.assertEqual(coverage_data['serial'], 'CAM-001')
        self.assertEqual(coverage_data['image_path'], self.coverage.image_path)

    def test_does_not_leak_data_from_other_chunks(self):
        other_user = User.objects.create_user(
            username='otherchunkuser', password='pass', stones_storage_edge='other-bucket',
        )
        other_chunk = StonesDetectionChunk.objects.create(
            user=other_user,
            date='2026-04-29',
            chunk=3,
            type=StonesDetectionChunk.TYPE_PREDICTIONS,
            gcs_path='otherchunkuser/2026-04-29/3/predictions/',
            processing_start_date='2026-04-29T16:00:00Z',
            status=StonesDetectionChunk.STATUS_PROCESSING,
        )
        EdgePrediction.objects.create(
            uuid='pred-uuid-other',
            chunk=other_chunk,
            serial='CAM-002',
            version='1',
            predictions=[],
            image_path='otherchunkuser/2026-04-29/3/predictions/pred-uuid-other/pred-uuid-other.jpg',
        )

        response = self._get()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(len(response.data['predictions']), 1)
        self.assertEqual(response.data['predictions'][0]['serial'], 'CAM-001')

    def test_empty_lists_when_chunk_has_no_data(self):
        response = self._get(chunk='5')

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data['predictions'], [])
        self.assertEqual(response.data['coverage'], [])

    @mock.patch('user.models.EdgePrediction.objects.filter')
    def test_db_failure_returns_500(self, mock_filter):
        mock_filter.side_effect = Exception('Database connection error')
        response = self._get()
        self.assertEqual(response.status_code, HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(
            response.data['detail'], 'Failed to fetch chunk data from database.'
        )


class UploadMissionsRemoveFilesTestCase(UserBase):
    fixtures = (
        'user/fixtures/user_fixtures.json',
        'aoi/fixtures/notebook_fixtures.json',
    )

    _DEFAULT_UPLOAD_CONFIG = {
        'unit_folder': 'unit',
        'upload': {
            'data_video': 'DCIM',
            'log': 'GPS_LOG',
            'calibration_video': None,
        }
    }

    def setUp(self):
        super().setUp()
        from aoi.models import Component
        component = Component.objects.create(
            name='Remove Files Component',
            image='test-image',
            upload_config=self._DEFAULT_UPLOAD_CONFIG,
        )
        self.ex_2_user.stone_google_folder = 'test-bucket'
        self.ex_2_user.default_upload_component = component
        self.ex_2_user.save(update_fields=['stone_google_folder', 'default_upload_component'])
        self.component = component

    def _make_completed_mission(self, uploaded_files):
        return UploadMissions.objects.create(
            user=self.ex_2_user,
            gcs_path='2024/2024-01-01_10-00-00',
            status=UploadMissions.STATUS_COMPLETED,
            component=self.component,
            uploaded_files=uploaded_files,
        )

    def _mock_gcs(self):
        mock_client = mock.MagicMock()
        mock_bucket = mock.MagicMock()
        mock_client.bucket.return_value = mock_bucket
        return mock_client, mock_bucket

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_suggest_delete_when_all_videos_removed(self, mock_gcs_cls):
        mock_client, _ = self._mock_gcs()
        mock_gcs_cls.return_value = mock_client

        mission = self._make_completed_mission([
            {'name': 'video.mp4', 'type': 'data_video', 'size': 1024},
        ])
        self.client.force_login(self.ex_2_user)
        url = reverse('upload_mission_remove_files', kwargs={'pk': mission.pk})
        response = self.client.post(url, {'files_to_remove': ['video.mp4']}, format='json')

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertTrue(response.data.get('suggest_delete'))

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_no_suggest_delete_when_videos_remain(self, mock_gcs_cls):
        mock_client, _ = self._mock_gcs()
        mock_gcs_cls.return_value = mock_client

        mission = self._make_completed_mission([
            {'name': 'video1.mp4', 'type': 'data_video', 'size': 1024},
            {'name': 'video2.mp4', 'type': 'data_video', 'size': 2048},
        ])
        self.client.force_login(self.ex_2_user)
        url = reverse('upload_mission_remove_files', kwargs={'pk': mission.pk})
        response = self.client.post(url, {'files_to_remove': ['video1.mp4']}, format='json')

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertNotIn('suggest_delete', response.data)

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_suggest_delete_when_only_log_remains_after_video_removed(self, mock_gcs_cls):
        """Removing the only video while a log file remains still triggers suggest_delete."""
        mock_client, _ = self._mock_gcs()
        mock_gcs_cls.return_value = mock_client

        mission = self._make_completed_mission([
            {'name': 'video.mp4', 'type': 'data_video', 'size': 1024},
            {'name': 'gps.log', 'type': 'log', 'size': 512},
        ])
        self.client.force_login(self.ex_2_user)
        url = reverse('upload_mission_remove_files', kwargs={'pk': mission.pk})
        response = self.client.post(url, {'files_to_remove': ['video.mp4']}, format='json')

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertTrue(response.data.get('suggest_delete'))

    @mock.patch('user.views.storage.Client.from_service_account_json')
    def test_suggest_delete_skips_trajectory_request_creation(self, mock_gcs_cls):
        """When all videos are removed no new trajectory request should be created."""
        mock_client, _ = self._mock_gcs()
        mock_gcs_cls.return_value = mock_client

        mission = self._make_completed_mission([
            {'name': 'video.mp4', 'type': 'data_video', 'size': 1024},
        ])
        self.client.force_login(self.ex_2_user)
        url = reverse('upload_mission_remove_files', kwargs={'pk': mission.pk})
        self.client.post(url, {'files_to_remove': ['video.mp4']}, format='json')

        mission.refresh_from_db()
        self.assertIsNone(mission.trajectory_request_id)


# ---------------------------------------------------------------------------
# process_closed_chunks management command
# ---------------------------------------------------------------------------

class ProcessClosedChunksTest(APITestCase):

    def setUp(self):
        from aoi.models import Component
        self.user = User.objects.create_user(
            username='chunkuser',
            password='pass',
            stones_storage_edge='test-bucket',
        )
        self.component = Component.objects.create(name='Edge Detection Assembler', image='gpx-image')

    def _make_pending_chunk(self, boundary):
        return StonesDetectionChunk.objects.create(
            user=self.user,
            date=boundary.date(),
            chunk=boundary.hour // 4,
            type=StonesDetectionChunk.TYPE_PREDICTIONS,
            gcs_path=f'chunkuser/{boundary.date()}/{boundary.hour // 4}/predictions/',
            processing_start_date=boundary,
            status=StonesDetectionChunk.STATUS_PENDING,
        )

    @mock.patch('user.management.commands.process_closed_chunks.datetime')
    def test_no_pending_chunks_does_nothing(self, mock_dt):
        from django.core.management import call_command
        from datetime import datetime, timezone
        boundary = datetime(2026, 4, 29, 8, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = boundary
        call_command('process_closed_chunks')
        from aoi.models import Request
        self.assertEqual(Request.objects.filter(component=self.component).count(), 0)

    @mock.patch('user.management.commands.process_closed_chunks.datetime')
    def test_missing_component_logs_error_and_skips(self, mock_dt):
        from django.core.management import call_command
        from datetime import datetime, timezone
        from aoi.models import Component
        Component.objects.filter(name='Edge Detection Assembler').delete()
        boundary = datetime(2026, 4, 29, 8, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = boundary
        self._make_pending_chunk(boundary)
        call_command('process_closed_chunks')
        chunk = StonesDetectionChunk.objects.get(user=self.user)
        self.assertEqual(chunk.status, StonesDetectionChunk.STATUS_PENDING)

    @mock.patch('user.management.commands.process_closed_chunks.datetime')
    def test_user_without_google_folder_skips_chunk(self, mock_dt):
        from django.core.management import call_command
        from datetime import datetime, timezone
        self.user.stones_storage_edge = None
        self.user.save(update_fields=['stones_storage_edge'])
        boundary = datetime(2026, 4, 29, 8, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = boundary
        self._make_pending_chunk(boundary)
        call_command('process_closed_chunks')
        chunk = StonesDetectionChunk.objects.get(user=self.user)
        self.assertEqual(chunk.status, StonesDetectionChunk.STATUS_PENDING)
        self.assertIsNone(chunk.gpx_request)

    @mock.patch('user.management.commands.process_closed_chunks.datetime')
    def test_happy_path_creates_request_and_sets_processing(self, mock_dt):
        from django.core.management import call_command
        from datetime import datetime, timezone
        from aoi.models import Request
        boundary = datetime(2026, 4, 29, 8, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = boundary
        chunk = self._make_pending_chunk(boundary)
        call_command('process_closed_chunks')
        chunk.refresh_from_db()
        self.assertEqual(chunk.status, StonesDetectionChunk.STATUS_PROCESSING)
        self.assertIsNotNone(chunk.gpx_request)
        req = Request.objects.get(component=self.component, user=self.user)
        self.assertEqual(chunk.gpx_request_id, req.pk)
        expected_path = f'test-bucket/chunkuser/{boundary.date()}/{boundary.hour // 4}/'
        self.assertEqual(req.additional_parameter, expected_path)


# ---------------------------------------------------------------------------
# fill_edge_chunks management command
# ---------------------------------------------------------------------------

class FillEdgeChunksTest(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='user',
            password='pass',
            stones_storage_edge='test-bucket',
        )

    @staticmethod
    def _blob(name, metadata):
        blob = mock.MagicMock()
        blob.name = name
        blob.download_as_bytes.return_value = json.dumps(metadata).encode()
        return blob

    @staticmethod
    def _mock_client(blobs):
        mock_client = mock.MagicMock()
        mock_client.list_blobs.return_value = blobs
        return mock_client

    def _run(self, blobs, **options):
        from django.core.management import call_command
        with mock.patch('user.management.commands.fill_edge_chunks._gcs_client') as mock_gcs_fn:
            mock_gcs_fn.return_value = self._mock_client(blobs)
            call_command('fill_edge_chunks', **options)

    def test_no_users_with_bucket_does_nothing(self):
        self.user.stones_storage_edge = None
        self.user.save(update_fields=['stones_storage_edge'])
        self._run([])
        self.assertEqual(StonesDetectionChunk.objects.count(), 0)

    def test_creates_prediction_from_valid_blob(self):
        blob = self._blob(
            'user/2026-05-10/4/predictions/test-uuid-1234/test-uuid-1234.json',
            VALID_PREDICTIONS_METADATA,
        )
        self._run([blob])

        prediction = EdgePrediction.objects.get(uuid='test-uuid-1234')
        self.assertEqual(prediction.serial, VALID_PREDICTIONS_METADATA['serial'])
        self.assertEqual(prediction.model_name, VALID_PREDICTIONS_METADATA['model_name'])
        self.assertEqual(
            prediction.image_path,
            'user/2026-05-10/4/predictions/test-uuid-1234/test-uuid-1234.jpg',
        )
        self.assertEqual(prediction.captured_at, datetime(2026, 4, 10, 7, 55, 13, tzinfo=timezone.utc))
        self.assertEqual(prediction.speed, 0.0)

        chunk = prediction.chunk
        self.assertEqual(chunk.user, self.user)
        self.assertEqual(chunk.date.isoformat(), '2026-05-10')
        self.assertEqual(chunk.chunk, 4)
        self.assertEqual(chunk.type, StonesDetectionChunk.TYPE_PREDICTIONS)
        self.assertEqual(chunk.status, StonesDetectionChunk.STATUS_DONE)

    def test_creates_coverage_from_valid_blob(self):
        blob = self._blob(
            'user/2026-05-10/4/coverage/test-uuid-5678/test-uuid-5678.json',
            VALID_COVERAGE_METADATA,
        )
        self._run([blob])

        coverage = EdgeCoverage.objects.get(uuid='test-uuid-5678')
        self.assertEqual(coverage.serial, VALID_COVERAGE_METADATA['serial'])
        self.assertEqual(coverage.chunk.type, StonesDetectionChunk.TYPE_COVERAGE)
        self.assertEqual(coverage.chunk.status, StonesDetectionChunk.STATUS_UPLOADING)
        self.assertEqual(coverage.captured_at, datetime(2026, 4, 10, 7, 55, 13, tzinfo=timezone.utc))
        self.assertEqual(coverage.speed, 0.0)

    def test_skips_existing_uuid(self):
        from datetime import date, datetime, timezone
        chunk = StonesDetectionChunk.objects.create(
            user=self.user, date=date(2026, 5, 10), chunk=4, type=StonesDetectionChunk.TYPE_PREDICTIONS,
            gcs_path='user/2026-05-10/4/predictions/',
            processing_start_date=datetime(2026, 5, 10, 20, 0, 0, tzinfo=timezone.utc),
            status=StonesDetectionChunk.STATUS_DONE,
        )
        EdgePrediction.objects.create(uuid='test-uuid-1234', chunk=chunk, serial='CAM-001')

        blob = self._blob(
            'user/2026-05-10/4/predictions/test-uuid-1234/test-uuid-1234.json',
            VALID_PREDICTIONS_METADATA,
        )
        self._run([blob])

        self.assertEqual(EdgePrediction.objects.filter(uuid='test-uuid-1234').count(), 1)

    def test_dry_run_creates_nothing(self):
        blob = self._blob(
            'user/2026-05-10/4/predictions/test-uuid-1234/test-uuid-1234.json',
            VALID_PREDICTIONS_METADATA,
        )
        self._run([blob], dry_run=True)

        self.assertFalse(EdgePrediction.objects.filter(uuid='test-uuid-1234').exists())
        self.assertEqual(StonesDetectionChunk.objects.count(), 0)

    def test_limit_stops_after_n(self):
        blobs = [
            self._blob(
                f'user/2026-05-10/4/predictions/uuid-{i}/uuid-{i}.json',
                {**VALID_PREDICTIONS_METADATA, 'uuid': f'uuid-{i}'},
            )
            for i in range(3)
        ]
        self._run(blobs, limit=1)

        self.assertEqual(EdgePrediction.objects.count(), 1)

    def test_invalid_metadata_is_skipped(self):
        incomplete = {'uuid': 'test-uuid-1234', 'version': '1'}  # missing gprmc/serial
        blob = self._blob(
            'user/2026-05-10/4/predictions/test-uuid-1234/test-uuid-1234.json',
            incomplete,
        )
        self._run([blob])

        self.assertFalse(EdgePrediction.objects.filter(uuid='test-uuid-1234').exists())
        self.assertEqual(StonesDetectionChunk.objects.count(), 0)

    def test_non_matching_blob_name_is_ignored(self):
        blob = self._blob('user/some_other_file.txt', {})
        self._run([blob])
        self.assertEqual(StonesDetectionChunk.objects.count(), 0)

    def test_uuid_mismatch_between_path_and_metadata_is_skipped(self):
        blob = self._blob(
            'user/2026-05-10/4/predictions/folder-uuid/folder-uuid.json',
            {**VALID_PREDICTIONS_METADATA, 'uuid': 'different-uuid'},
        )
        self._run([blob])
        self.assertEqual(EdgePrediction.objects.count(), 0)

    def test_username_filter_scopes_to_one_user(self):
        other_user = User.objects.create_user(
            username='OtherUserr', password='pass', stones_storage_edge='other-bucket',
        )
        blob = self._blob(
            'user/2026-05-10/4/predictions/uuid-a/uuid-a.json',
            {**VALID_PREDICTIONS_METADATA, 'uuid': 'uuid-a'},
        )
        self._run([blob], username='user')

        self.assertTrue(EdgePrediction.objects.filter(uuid='uuid-a').exists())
        self.assertFalse(StonesDetectionChunk.objects.filter(user=other_user).exists())

    def test_existing_chunk_status_is_not_overwritten(self):
        """A chunk that already exists (e.g. status=failed from a botched GPX
        run) keeps its status - fill_edge_chunks only fills in missing
        prediction/coverage rows, it never touches the status of a chunk
        that already exists."""
        from datetime import date, datetime, timezone
        chunk = StonesDetectionChunk.objects.create(
            user=self.user, date=date(2026, 5, 10), chunk=4, type=StonesDetectionChunk.TYPE_PREDICTIONS,
            gcs_path='user/2026-05-10/4/predictions/',
            processing_start_date=datetime(2026, 5, 10, 20, 0, 0, tzinfo=timezone.utc),
            status=StonesDetectionChunk.STATUS_FAILED,
        )
        blob = self._blob(
            'user/2026-05-10/4/predictions/test-uuid-1234/test-uuid-1234.json',
            VALID_PREDICTIONS_METADATA,
        )
        self._run([blob])

        chunk.refresh_from_db()
        self.assertEqual(chunk.status, StonesDetectionChunk.STATUS_FAILED)
        self.assertTrue(EdgePrediction.objects.filter(uuid='test-uuid-1234', chunk=chunk).exists())


# ---------------------------------------------------------------------------
# backfill_captured_at_speed management command
# ---------------------------------------------------------------------------

class BackfillCapturedAtSpeedTest(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='backfilluser', password='pass')
        self.coverage_chunk = StonesDetectionChunk.objects.create(
            user=self.user, date='2026-05-10', chunk=4, type=StonesDetectionChunk.TYPE_COVERAGE,
            gcs_path='backfilluser/2026-05-10/4/coverage/',
            processing_start_date=datetime(2026, 5, 10, 20, 0, 0, tzinfo=timezone.utc),
        )
        self.prediction_chunk = StonesDetectionChunk.objects.create(
            user=self.user, date='2026-05-10', chunk=4, type=StonesDetectionChunk.TYPE_PREDICTIONS,
            gcs_path='backfilluser/2026-05-10/4/predictions/',
            processing_start_date=datetime(2026, 5, 10, 20, 0, 0, tzinfo=timezone.utc),
        )

    @staticmethod
    def _run(**options):
        from django.core.management import call_command
        call_command('backfill_captured_at_speed', **options)

    def test_valid_gprmc_populates_fields(self):
        coverage = EdgeCoverage.objects.create(
            uuid='cov-valid', chunk=self.coverage_chunk, serial='CAM-001',
            gprmc=VALID_COVERAGE_METADATA['gprmc'],
        )
        self._run()
        coverage.refresh_from_db()
        self.assertEqual(coverage.captured_at, datetime(2026, 4, 10, 7, 55, 13, tzinfo=timezone.utc))
        self.assertEqual(coverage.speed, 0.0)

    def test_invalid_gprmc_stays_none(self):
        coverage = EdgeCoverage.objects.create(
            uuid='cov-void', chunk=self.coverage_chunk, serial='CAM-001',
            gprmc='$GPRMC,123519,V,,,,,,,230394,,*33',
        )
        self._run()
        coverage.refresh_from_db()
        self.assertIsNone(coverage.captured_at)
        self.assertIsNone(coverage.speed)

    def test_covers_both_models(self):
        coverage = EdgeCoverage.objects.create(
            uuid='cov-valid-2', chunk=self.coverage_chunk, serial='CAM-001',
            gprmc=VALID_COVERAGE_METADATA['gprmc'],
        )
        prediction = EdgePrediction.objects.create(
            uuid='pred-valid', chunk=self.prediction_chunk, serial='CAM-001',
            gprmc=VALID_PREDICTIONS_METADATA['gprmc'],
        )
        self._run()
        coverage.refresh_from_db()
        prediction.refresh_from_db()
        self.assertIsNotNone(coverage.captured_at)
        self.assertIsNotNone(prediction.captured_at)

    def test_dry_run_makes_no_db_changes(self):
        coverage = EdgeCoverage.objects.create(
            uuid='cov-dry', chunk=self.coverage_chunk, serial='CAM-001',
            gprmc=VALID_COVERAGE_METADATA['gprmc'],
        )
        self._run(dry_run=True)
        coverage.refresh_from_db()
        self.assertIsNone(coverage.captured_at)
        self.assertIsNone(coverage.speed)

    def test_idempotent_on_rerun(self):
        coverage = EdgeCoverage.objects.create(
            uuid='cov-rerun', chunk=self.coverage_chunk, serial='CAM-001',
            gprmc=VALID_COVERAGE_METADATA['gprmc'],
        )
        self._run()
        self._run()
        coverage.refresh_from_db()
        self.assertEqual(coverage.captured_at, datetime(2026, 4, 10, 7, 55, 13, tzinfo=timezone.utc))
        self.assertEqual(coverage.speed, 0.0)

    def test_rows_without_gprmc_are_left_alone(self):
        coverage = EdgeCoverage.objects.create(
            uuid='cov-nogprmc', chunk=self.coverage_chunk, serial='CAM-001', gprmc=None,
        )
        self._run()  # should not raise
        coverage.refresh_from_db()
        self.assertIsNone(coverage.captured_at)


# ---------------------------------------------------------------------------
# sync_stones_chunk_status signal
# ---------------------------------------------------------------------------

class SyncStonesChunkStatusSignalTest(APITestCase):

    def setUp(self):
        from aoi.models import Component, Request
        self.user = User.objects.create_user(username='signaluser', password='pass')
        self.component = Component.objects.create(name='Stone GPX Signal', image='gpx-image')
        self.request = Request.objects.create(user=self.user, component=self.component)
        self.chunk = StonesDetectionChunk.objects.create(
            user=self.user,
            date='2026-04-29',
            chunk=2,
            type=StonesDetectionChunk.TYPE_PREDICTIONS,
            gcs_path='signaluser/2026-04-29/2/predictions/',
            processing_start_date='2026-04-29T08:00:00Z',
            status=StonesDetectionChunk.STATUS_PROCESSING,
            gpx_request=self.request,
        )

    def test_calculated_true_sets_chunk_done(self):
        self.request.calculated = True
        self.request.save(update_fields=['calculated'])
        self.chunk.refresh_from_db()
        self.assertEqual(self.chunk.status, StonesDetectionChunk.STATUS_DONE)

    def test_error_set_sets_chunk_failed(self):
        self.request.error = 'something went wrong'
        self.request.save(update_fields=['error'])
        self.chunk.refresh_from_db()
        self.assertEqual(self.chunk.status, StonesDetectionChunk.STATUS_FAILED)

    def test_no_relevant_change_leaves_chunk_unchanged(self):
        self.request.additional_parameter = 'new-path'
        self.request.save(update_fields=['additional_parameter'])
        self.chunk.refresh_from_db()
        self.assertEqual(self.chunk.status, StonesDetectionChunk.STATUS_PROCESSING)

    def test_request_without_chunk_does_not_raise(self):
        from aoi.models import Request
        orphan = Request.objects.create(user=self.user, component=self.component)
        orphan.calculated = True
        orphan.save(update_fields=['calculated'])


class DayWindowTestCase(SimpleTestCase):
    def test_normal_day(self):
        start, end = day_window(date(2026, 8, 26), 'America/Winnipeg')
        self.assertEqual(start, datetime(2026, 8, 26, 5, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 8, 27, 5, 0, tzinfo=timezone.utc))
        self.assertEqual(end - start, timedelta(hours=24))

    def test_spring_forward_23_hour_day(self):
        start, end = day_window(date(2026, 3, 8), 'America/Winnipeg')
        self.assertEqual(start, datetime(2026, 3, 8, 6, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc))
        self.assertEqual(end - start, timedelta(hours=23))

    def test_fall_back_25_hour_day(self):
        start, end = day_window(date(2026, 11, 1), 'America/Winnipeg')
        self.assertEqual(start, datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc))
        self.assertEqual(end - start, timedelta(hours=25))

    def test_no_dst_zone_regina(self):
        start, end = day_window(date(2026, 3, 8), 'America/Regina')
        self.assertEqual(start, datetime(2026, 3, 8, 6, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 3, 9, 6, 0, tzinfo=timezone.utc))
        self.assertEqual(end - start, timedelta(hours=24))


class UnitListAPIViewTestCase(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='unituser', password='pass')
        self.camera = Camera.objects.create(cam_serial_num='CAM-100', user=self.user)

    def _make_chunk(self, user, chunk=0):
        return StonesDetectionChunk.objects.create(
            user=user,
            date='2026-04-29',
            chunk=chunk,
            type=StonesDetectionChunk.TYPE_COVERAGE,
            gcs_path=f'{user.username}/2026-04-29/{chunk}/coverage/',
            processing_start_date='2026-04-29T12:00:00Z',
            status=StonesDetectionChunk.STATUS_PROCESSING,
        )

    def _set_created_at(self, uuid, created_at):
        EdgeCoverage.objects.filter(uuid=uuid).update(created_at=created_at)

    def test_unauthenticated_returns_403(self):
        response = self.client.get(reverse('unit_list'))
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    def test_response_shape_has_no_tier_or_staff(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('unit_list'))
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertIn('timezone', response.data)
        self.assertIn('server_time', response.data)
        self.assertIn('units', response.data)
        response_str = json.dumps(response.data, default=str)
        self.assertNotIn('tier', response_str)
        self.assertNotIn('staff', response_str)

    def test_camera_with_no_coverage_appears_with_null_fields(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('unit_list'))
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(len(response.data['units']), 1)
        unit = response.data['units'][0]
        self.assertEqual(unit['unit_id'], 'CAM-100')
        self.assertEqual(unit['machine_label'], 'CAM-100')
        for field in ('last_received_at', 'last_captured_at', 'last_lat', 'last_lng', 'has_recent_image'):
            self.assertIsNone(unit[field])

    def test_coverage_with_invalid_gps_fix_has_null_position(self):
        # A coverage row can exist (real received/captured time, an image)
        # with location still null - the GPS fix was invalid at that moment.
        # Distinct from "no coverage at all": only lat/lng should be null.
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='cov-no-fix',
            chunk=chunk,
            serial='CAM-100',
            captured_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            location=None,
            image_path='frame.jpg',
        )
        self._set_created_at('cov-no-fix', datetime(2026, 6, 1, tzinfo=timezone.utc))

        self.client.force_login(self.user)
        response = self.client.get(reverse('unit_list'))

        self.assertEqual(response.status_code, HTTP_200_OK)
        unit = response.data['units'][0]
        self.assertIsNone(unit['last_lat'])
        self.assertIsNone(unit['last_lng'])
        self.assertIsNotNone(unit['last_received_at'])
        self.assertIsNotNone(unit['last_captured_at'])
        self.assertEqual(unit['has_recent_image'], True)

    def test_camera_owned_by_other_user_is_excluded(self):
        other_user = User.objects.create_user(username='otherunituser', password='pass')
        Camera.objects.create(cam_serial_num='CAM-OTHER', user=other_user)

        self.client.force_login(self.user)
        response = self.client.get(reverse('unit_list'))

        self.assertEqual(response.status_code, HTTP_200_OK)
        serials = [unit['unit_id'] for unit in response.data['units']]
        self.assertEqual(serials, ['CAM-100'])

    def test_coverage_from_reassigned_serial_is_not_attached(self):
        # Simulate serial reuse/reassignment: an EdgeCoverage row matches
        # self.camera's serial, but its chunk belongs to a different user.
        other_user = User.objects.create_user(username='otherunituser2', password='pass')
        other_chunk = self._make_chunk(other_user, chunk=1)
        EdgeCoverage.objects.create(
            uuid='cov-leak-1',
            chunk=other_chunk,
            serial='CAM-100',
            image_path='leak.jpg',
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('unit_list'))

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(len(response.data['units']), 1)
        unit = response.data['units'][0]
        for field in ('last_received_at', 'last_captured_at', 'last_lat', 'last_lng', 'has_recent_image'):
            self.assertIsNone(unit[field])

    def test_latest_created_at_row_wins_and_fields_are_not_mixed(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='cov-older',
            chunk=chunk,
            serial='CAM-100',
            captured_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            location=Point(10.0, 20.0, srid=4326),
            image_path='older.jpg',
        )
        self._set_created_at('cov-older', datetime(2026, 4, 1, tzinfo=timezone.utc))

        EdgeCoverage.objects.create(
            uuid='cov-newer',
            chunk=chunk,
            serial='CAM-100',
            captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),  # earlier captured_at
            location=Point(30.0, 40.0, srid=4326),
            image_path=None,
        )
        self._set_created_at('cov-newer', datetime(2026, 5, 1, tzinfo=timezone.utc))

        self.client.force_login(self.user)
        response = self.client.get(reverse('unit_list'))

        self.assertEqual(response.status_code, HTTP_200_OK)
        unit = response.data['units'][0]
        self.assertEqual(unit['last_received_at'][:10], '2026-05-01')
        self.assertEqual(unit['last_captured_at'][:10], '2026-01-01')
        self.assertEqual(unit['last_lat'], 40.0)
        self.assertEqual(unit['last_lng'], 30.0)
        self.assertEqual(unit['has_recent_image'], False)  # not None - distinguishes "has row, no image" from "no row"

    def test_unit_id_and_machine_label_are_both_serial(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('unit_list'))
        unit = response.data['units'][0]
        self.assertEqual(unit['unit_id'], unit['machine_label'])
        self.assertEqual(unit['unit_id'], self.camera.cam_serial_num)

    def test_multiple_owned_cameras_and_one_not_owned(self):
        camera2 = Camera.objects.create(cam_serial_num='CAM-101', user=self.user)
        other_user = User.objects.create_user(username='otherunituser3', password='pass')
        Camera.objects.create(cam_serial_num='CAM-NOT-OWNED', user=other_user)

        self.client.force_login(self.user)
        response = self.client.get(reverse('unit_list'))

        serials = sorted(unit['unit_id'] for unit in response.data['units'])
        self.assertEqual(serials, ['CAM-100', 'CAM-101'])

    def test_query_count_is_constant_regardless_of_camera_count(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(uuid='cov-a', chunk=chunk, serial='CAM-100')

        camera2 = Camera.objects.create(cam_serial_num='CAM-101', user=self.user)
        chunk2 = self._make_chunk(self.user, chunk=1)
        EdgeCoverage.objects.create(uuid='cov-b', chunk=chunk2, serial='CAM-101')

        Camera.objects.create(cam_serial_num='CAM-102', user=self.user)

        self.client.force_authenticate(self.user)
        with self.assertNumQueries(2):
            response = self.client.get(reverse('unit_list'))

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(len(response.data['units']), 3)


class UnitTelemetryAPIViewTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='telemetryuser', password='pass', timezone='America/Regina')
        self.camera = Camera.objects.create(cam_serial_num='TEL-100', user=self.user)

    def _make_chunk(self, user, chunk=0, type=StonesDetectionChunk.TYPE_COVERAGE):
        return StonesDetectionChunk.objects.create(
            user=user,
            date='2026-06-01',
            chunk=chunk,
            type=type,
            gcs_path=f'{user.username}/2026-06-01/{chunk}/{type}/',
            processing_start_date='2026-06-01T12:00:00Z',
            status=StonesDetectionChunk.STATUS_PROCESSING,
        )

    def _set_created_at(self, model, uuid, created_at):
        model.objects.filter(uuid=uuid).update(created_at=created_at)

    @staticmethod
    def _iso(value):
        # from/to are datetime objects; per-unit fields are ISO strings.
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value.replace('Z', '+00:00'))

    def _get(self, **params):
        self.client.force_login(self.user)
        return self.client.get(reverse('unit_telemetry'), params)

    # -- auth / param validation --------------------------------------

    def test_unauthenticated_returns_403(self):
        response = self.client.get(reverse('unit_telemetry'), {'day': '2026-06-01'})
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    def test_both_day_and_rolling_returns_400(self):
        response = self._get(day='2026-06-01', rolling='true')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_neither_day_nor_rolling_returns_400(self):
        response = self._get()
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_malformed_day_returns_400(self):
        response = self._get(day='not-a-date')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_calendar_invalid_day_returns_400(self):
        response = self._get(day='2026-13-01')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_non_truthy_rolling_returns_400(self):
        response = self._get(rolling='false')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    # -- ownership -------------------------------------------------------

    def test_foreign_unit_id_returns_404_not_403(self):
        other_user = User.objects.create_user(username='telemetryother', password='pass')
        Camera.objects.create(cam_serial_num='TEL-OTHER', user=other_user)
        response = self._get(day='2026-06-01', unit_id='TEL-OTHER')
        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)

    def test_unit_id_filters_to_a_single_unit(self):
        Camera.objects.create(cam_serial_num='TEL-101', user=self.user)
        response = self._get(day='2026-06-01', unit_id='TEL-100')
        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(len(response.data['units']), 1)
        self.assertEqual(response.data['units'][0]['unit_id'], 'TEL-100')

    def test_coverage_from_reassigned_serial_is_not_attached(self):
        # Same serial, but the chunk belongs to a different account
        other_user = User.objects.create_user(username='telemetryother2', password='pass')
        other_chunk = self._make_chunk(other_user, chunk=1)
        EdgeCoverage.objects.create(
            uuid='tel-cov-leak',
            chunk=other_chunk,
            serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326),
            image_path='leak.jpg',
        )
        response = self._get(day='2026-06-01')
        self.assertEqual(response.status_code, HTTP_200_OK)
        unit = response.data['units'][0]
        self.assertEqual(unit['totals']['messages'], 0)
        self.assertEqual(unit['track'], [])

    # -- window resolution -------------------------------------------------

    def test_day_mode_window_matches_day_window_across_dst_fixtures(self):
        fixtures = [
            ('America/Winnipeg', date(2026, 8, 26)),   # 24h
            ('America/Winnipeg', date(2026, 3, 8)),    # 23h spring-forward
            ('America/Winnipeg', date(2026, 11, 1)),   # 25h fall-back
            ('America/Regina', date(2026, 3, 8)),      # no DST
        ]
        for tz_name, day in fixtures:
            with self.subTest(tz=tz_name, day=day):
                self.user.timezone = tz_name
                self.user.save(update_fields=['timezone'])
                expected_start, expected_end = day_window(day, tz_name)

                response = self._get(day=day.isoformat())

                self.assertEqual(response.status_code, HTTP_200_OK)
                self.assertEqual(self._iso(response.data['from']), expected_start)
                self.assertEqual(self._iso(response.data['to']), expected_end)
                self.assertEqual(
                    len(response.data['units'][0]['buckets']),
                    int((expected_end - expected_start).total_seconds() // 900),
                )

    def test_rolling_mode_is_trailing_24h_ending_now(self):
        before = dj_timezone.now()
        response = self._get(rolling='true')
        after = dj_timezone.now()

        self.assertEqual(response.status_code, HTTP_200_OK)
        to = self._iso(response.data['to'])
        from_ = self._iso(response.data['from'])
        self.assertTrue(before <= to <= after + timedelta(seconds=5))
        self.assertEqual(to - from_, timedelta(hours=24))

    # -- captured_at/created_at fallback -------------------------------

    def test_captured_at_null_falls_back_to_created_at(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='tel-cov-nofix',
            chunk=chunk,
            serial='TEL-100',
            captured_at=None,
            location=None,
            image_path=None,
        )
        self._set_created_at(EdgeCoverage, 'tel-cov-nofix', datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc))

        response = self._get(day='2026-06-01')

        self.assertEqual(response.status_code, HTTP_200_OK)
        unit = response.data['units'][0]
        self.assertEqual(unit['totals']['messages'], 1)
        self.assertEqual(self._iso(unit['totals']['first_at']), datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc))

    # -- union-of-both-tables vs coverage-only ----------------------------

    def test_totals_reflect_union_but_buckets_are_coverage_only(self):
        chunk = self._make_chunk(self.user)
        pred_chunk = self._make_chunk(self.user, chunk=1, type=StonesDetectionChunk.TYPE_PREDICTIONS)

        EdgeCoverage.objects.create(
            uuid='tel-cov-1', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path='cov.jpg',
        )
        EdgePrediction.objects.create(
            uuid='tel-pred-1', chunk=pred_chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 9, 30, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326),
            predictions=[{'confidence': 0.9}],
            image_path='pred.jpg',
        )

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        totals = unit['totals']
        self.assertEqual(totals['messages'], 2)
        self.assertEqual(totals['images'], 2)
        self.assertEqual(totals['detections'], 1)
        self.assertEqual(self._iso(totals['first_at']), datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc))
        self.assertEqual(self._iso(totals['last_at']), datetime(2026, 6, 1, 9, 30, tzinfo=timezone.utc))

        # Prediction lands in bucket 14, which has no coverage - must read 0.
        self.assertEqual(unit['buckets'][14], 0)

    def test_no_detections_when_no_predictions_exist(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='tel-cov-nodet', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path='cov.jpg',
        )
        response = self._get(day='2026-06-01')
        unit = response.data['units'][0]
        self.assertEqual(unit['totals']['detections'], 0)
        self.assertTrue(all(p['det'] == 0 for p in unit['track']))

    def test_gap_minutes_counts_quiet_time_between_coverage_messages(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='tel-cov-a', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path=None,
        )
        EdgeCoverage.objects.create(
            uuid='tel-cov-b', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 45, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path=None,
        )
        response = self._get(day='2026-06-01')
        unit = response.data['units'][0]
        self.assertEqual(unit['totals']['gap_minutes'], 30)

    def test_gap_minutes_is_zero_with_a_single_coverage_message(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='tel-cov-solo', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path=None,
        )
        response = self._get(day='2026-06-01')
        unit = response.data['units'][0]
        self.assertEqual(unit['totals']['gap_minutes'], 0)

    def test_predictions_are_not_used_as_a_liveness_signal_for_gap_minutes(self):
        chunk = self._make_chunk(self.user)
        pred_chunk = self._make_chunk(self.user, chunk=1, type=StonesDetectionChunk.TYPE_PREDICTIONS)

        EdgeCoverage.objects.create(
            uuid='tel-cov-c', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path=None,
        )
        EdgeCoverage.objects.create(
            uuid='tel-cov-d', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 45, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path=None,
        )
        # A stray prediction lands in the middle of the coverage gap. It must
        # not be treated as a heartbeat and must not shrink gap_minutes.
        EdgePrediction.objects.create(
            uuid='tel-pred-mid-gap', chunk=pred_chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 20, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326),
            predictions=[{'confidence': 0.5}], image_path=None,
        )

        response = self._get(day='2026-06-01')
        unit = response.data['units'][0]
        self.assertEqual(unit['totals']['gap_minutes'], 30)

    # -- distance / track ---------------------------------------------------

    def test_distance_correctness(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='tel-cov-p1', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path=None,
        )
        EdgeCoverage.objects.create(
            uuid='tel-cov-p2', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 5, tzinfo=timezone.utc),
            location=Point(-98.0, 50.1, srid=4326), image_path=None,
        )
        response = self._get(day='2026-06-01')
        unit = response.data['units'][0]
        # ~0.1 degree latitude is ~11.0-11.2 real km; loose bounds, not exact.
        self.assertGreaterEqual(unit['totals']['distance_km'], 11.0)
        self.assertLessEqual(unit['totals']['distance_km'], 11.2)
        self.assertEqual(len(unit['track']), 2)

    def test_track_conserves_detections_when_coordinates_repeat(self):
        # Several messages at the exact same location (stationary unit, or a
        # stuck GPS clock) must not lose detections when track points collapse.
        chunk = self._make_chunk(self.user)
        pred_chunk = self._make_chunk(self.user, chunk=1, type=StonesDetectionChunk.TYPE_PREDICTIONS)
        same_point = Point(-98.0, 50.0, srid=4326)

        for i in range(4):
            EdgeCoverage.objects.create(
                uuid=f'tel-cov-dup-{i}', chunk=chunk, serial='TEL-100',
                captured_at=datetime(2026, 6, 1, 7, i, tzinfo=timezone.utc),
                location=same_point, image_path=None,
            )
        EdgePrediction.objects.create(
            uuid='tel-pred-dup', chunk=pred_chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 4, tzinfo=timezone.utc),
            location=same_point,
            predictions=[{'confidence': 0.9}, {'confidence': 0.8}, {'confidence': 0.7}],
            image_path=None,
        )

        response = self._get(day='2026-06-01')
        unit = response.data['units'][0]

        self.assertEqual(unit['totals']['detections'], 3)
        self.assertEqual(sum(p['det'] for p in unit['track']), 3)

    def test_track_point_cap(self):
        chunk = self._make_chunk(self.user)
        start = datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc)
        n = 1600
        rows = [
            EdgeCoverage(
                uuid=f'tel-cov-cap-{i}',
                chunk=chunk,
                serial='TEL-100',
                captured_at=start + timedelta(seconds=i * 10),
                # zigzag so simplify doesn't collapse the path before the cap kicks in
                location=Point(-98.0 + i * 0.0001, 50.0 + (0.01 if i % 2 == 0 else -0.01), srid=4326),
                image_path=None,
            )
            for i in range(n)
        ]
        EdgeCoverage.objects.bulk_create(rows)

        response = self._get(day='2026-06-01')
        unit = response.data['units'][0]
        self.assertLessEqual(len(unit['track']), 1500)
        self.assertEqual(unit['totals']['messages'], n)  # totals computed pre-decimation

    # -- range totals --------------------------------------

    def test_range_totals_narrow_to_the_requested_sub_range(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='tel-range-a', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path=None,
        )
        EdgeCoverage.objects.create(
            uuid='tel-range-b', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.1, srid=4326), image_path='shot.jpg',
        )
        EdgeCoverage.objects.create(
            uuid='tel-range-c', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 18, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.2, srid=4326), image_path=None,
        )

        response = self._get(
            day='2026-06-01',
            range_from='2026-06-01T11:00:00Z',
            range_to='2026-06-01T13:00:00Z',
        )

        self.assertEqual(response.status_code, HTTP_200_OK)
        unit = response.data['units'][0]
        self.assertEqual(unit['totals']['messages'], 1)
        self.assertEqual(unit['totals']['images'], 1)
        self.assertEqual(self._iso(unit['totals']['first_at']), datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(self._iso(unit['totals']['last_at']), datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc))
        # buckets/track stay full-window - only totals narrow.
        self.assertEqual(len(unit['buckets']), 96)

    def test_range_totals_full_window_matches_unscoped_totals(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='tel-range-full-a', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path=None,
        )
        EdgeCoverage.objects.create(
            uuid='tel-range-full-b', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 45, tzinfo=timezone.utc),
            location=Point(-98.0, 50.1, srid=4326), image_path=None,
        )

        plain = self._get(day='2026-06-01')
        scoped = self._get(
            day='2026-06-01',
            range_from='2026-06-01T06:00:00Z',
            range_to='2026-06-02T06:00:00Z',
        )

        self.assertEqual(plain.data['units'][0]['totals'], scoped.data['units'][0]['totals'])

    def test_range_totals_with_fewer_than_two_points_has_zero_distance(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='tel-range-solo', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path=None,
        )
        response = self._get(
            day='2026-06-01',
            range_from='2026-06-01T06:00:00Z',
            range_to='2026-06-01T08:00:00Z',
        )
        self.assertEqual(response.data['units'][0]['totals']['distance_km'], 0.0)

    def test_range_only_one_param_returns_400(self):
        response = self._get(day='2026-06-01', range_from='2026-06-01T06:00:00Z')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_range_malformed_datetime_returns_400(self):
        response = self._get(day='2026-06-01', range_from='not-a-time', range_to='2026-06-01T08:00:00Z')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_range_naive_datetime_returns_400(self):
        response = self._get(day='2026-06-01', range_from='2026-06-01T06:00:00', range_to='2026-06-01T08:00:00')
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_range_end_before_start_returns_400(self):
        response = self._get(
            day='2026-06-01', range_from='2026-06-01T08:00:00Z', range_to='2026-06-01T06:00:00Z',
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    def test_range_outside_resolved_window_returns_400(self):
        response = self._get(
            day='2026-06-01', range_from='2026-05-30T00:00:00Z', range_to='2026-05-31T00:00:00Z',
        )
        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)

    # -- empty state -----------------------------------------------------

    def test_unit_with_no_telemetry_still_appears_with_zeroed_totals(self):
        response = self._get(day='2026-06-01')

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(len(response.data['units']), 1)
        unit = response.data['units'][0]
        self.assertEqual(unit['unit_id'], 'TEL-100')
        self.assertEqual(unit['track'], [])
        self.assertEqual(unit['totals']['messages'], 0)
        self.assertIsNone(unit['totals']['first_at'])
        self.assertIsNone(unit['totals']['last_at'])
        self.assertEqual(len(unit['buckets']), 96)  # 24h / 15min, America/Regina has no DST
        self.assertTrue(all(b == 0 for b in unit['buckets']))


class UnitAlertsTestCase(UnitTelemetryAPIViewTestCase):
    """the `alerts` key on GET /api/units/telemetry"""

    def _rules(self, unit):
        return {alert['rule'] for alert in unit['alerts']}

    # -- empty state -------------------------------------------------------

    def test_ok_when_everything_is_normal(self):
        chunk = self._make_chunk(self.user)
        pred_chunk = self._make_chunk(self.user, chunk=1, type=StonesDetectionChunk.TYPE_PREDICTIONS)
        EdgeCoverage.objects.create(
            uuid='alert-cov-ok', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path='cov.jpg',
        )
        EdgePrediction.objects.create(
            uuid='alert-pred-ok', chunk=pred_chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 1, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326),
            predictions=[{'confidence': 0.9}], image_path='pred.jpg',
        )

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        self.assertEqual(unit['alerts'], [
            {'rule': 'ok', 'severity': 'ok', 'copy': "Everything looks normal for this unit."},
        ])

    # -- not_reporting / late -----------------------------------------------

    def test_not_reporting_when_last_coverage_is_over_an_hour_old(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='alert-cov-old', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path='cov.jpg',
        )
        self._set_created_at(EdgeCoverage, 'alert-cov-old', dj_timezone.now() - timedelta(hours=2))

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        self.assertIn('not_reporting', self._rules(unit))

    def test_late_when_last_coverage_is_between_5_minutes_and_an_hour_old(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='alert-cov-late', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path='cov.jpg',
        )
        self._set_created_at(EdgeCoverage, 'alert-cov-late', dj_timezone.now() - timedelta(minutes=30))

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        self.assertIn('late', self._rules(unit))

    def test_reporting_within_5_minutes_fires_neither(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='alert-cov-fresh', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path='cov.jpg',
        )

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        self.assertNotIn('not_reporting', self._rules(unit))
        self.assertNotIn('late', self._rules(unit))

    def test_just_under_5_minutes_is_still_reporting(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='alert-cov-boundary-5m-under', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path='cov.jpg',
        )
        self._set_created_at(EdgeCoverage, 'alert-cov-boundary-5m-under', dj_timezone.now() - timedelta(minutes=5) + timedelta(seconds=1))

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        self.assertNotIn('not_reporting', self._rules(unit))
        self.assertNotIn('late', self._rules(unit))

    def test_just_over_5_minutes_is_late(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='alert-cov-boundary-5m-over', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path='cov.jpg',
        )
        self._set_created_at(EdgeCoverage, 'alert-cov-boundary-5m-over', dj_timezone.now() - timedelta(minutes=5, seconds=1))

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        self.assertIn('late', self._rules(unit))
        self.assertNotIn('not_reporting', self._rules(unit))

    def test_just_under_1_hour_is_still_late(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='alert-cov-boundary-1h-under', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path='cov.jpg',
        )
        self._set_created_at(EdgeCoverage, 'alert-cov-boundary-1h-under', dj_timezone.now() - timedelta(hours=1) + timedelta(seconds=1))

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        self.assertIn('late', self._rules(unit))
        self.assertNotIn('not_reporting', self._rules(unit))

    def test_just_over_1_hour_is_not_reporting(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='alert-cov-boundary-1h-over', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path='cov.jpg',
        )
        self._set_created_at(EdgeCoverage, 'alert-cov-boundary-1h-over', dj_timezone.now() - timedelta(hours=1, seconds=1))

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        self.assertIn('not_reporting', self._rules(unit))
        self.assertNotIn('late', self._rules(unit))

    def test_no_coverage_ever_is_not_reporting_not_a_crash(self):
        response = self._get(day='2026-06-01')

        self.assertEqual(response.status_code, HTTP_200_OK)
        unit = response.data['units'][0]
        self.assertEqual(self._rules(unit), {'not_reporting'})

    # -- no_images -----------------------------------------------------------

    def test_no_images_fires_when_window_has_messages_but_no_image(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='alert-cov-noimg', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path=None,
        )

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        self.assertIn('no_images', self._rules(unit))

    def test_no_images_does_not_fire_on_a_fully_empty_window(self):
        chunk = self._make_chunk(self.user)
        # Real message exists, but outside the queried day - the window itself is empty.
        EdgeCoverage.objects.create(
            uuid='alert-cov-outside', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 5, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path='cov.jpg',
        )

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        self.assertEqual(unit['totals']['messages'], 0)
        self.assertNotIn('no_images', self._rules(unit))

    # -- no_gps_fix ------------------------------------------------------

    def test_no_gps_fix_when_every_coverage_message_has_a_null_location(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='alert-cov-nogps', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=None, image_path='cov.jpg',
        )

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        self.assertIn('no_gps_fix', self._rules(unit))

    def test_no_gps_fix_does_not_fire_when_any_message_has_a_location(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='alert-cov-mixed-1', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=None, image_path='cov.jpg',
        )
        EdgeCoverage.objects.create(
            uuid='alert-cov-mixed-2', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 5, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path='cov.jpg',
        )

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        self.assertNotIn('no_gps_fix', self._rules(unit))

    # -- detection_not_running ------------------------------------------

    def test_detection_not_running_when_coverage_present_but_no_predictions(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='alert-cov-nodet', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path='cov.jpg',
        )

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        self.assertIn('detection_not_running', self._rules(unit))

    def test_detection_not_running_does_not_fire_when_predictions_exist(self):
        chunk = self._make_chunk(self.user)
        pred_chunk = self._make_chunk(self.user, chunk=1, type=StonesDetectionChunk.TYPE_PREDICTIONS)
        EdgeCoverage.objects.create(
            uuid='alert-cov-hasdet', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326), image_path='cov.jpg',
        )
        EdgePrediction.objects.create(
            uuid='alert-pred-hasdet', chunk=pred_chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 1, tzinfo=timezone.utc),
            location=Point(-98.0, 50.0, srid=4326),
            predictions=[{'confidence': 0.9}], image_path='pred.jpg',
        )

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        self.assertNotIn('detection_not_running', self._rules(unit))

    # -- ordering -------------------------------------------------------

    def test_multiple_rules_fire_together_in_spec_order(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='alert-cov-multi', chunk=chunk, serial='TEL-100',
            captured_at=datetime(2026, 6, 1, 7, 0, tzinfo=timezone.utc),
            location=None, image_path=None,
        )
        self._set_created_at(EdgeCoverage, 'alert-cov-multi', dj_timezone.now() - timedelta(minutes=30))

        response = self._get(day='2026-06-01')

        unit = response.data['units'][0]
        self.assertEqual(
            [alert['rule'] for alert in unit['alerts']],
            ['late', 'no_images', 'no_gps_fix', 'detection_not_running'],
        )


class UnitLatestImageURLTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='imageuser', password='pass')
        self.user.stones_storage_edge = 'test-edge-bucket'
        self.user.save(update_fields=['stones_storage_edge'])
        self.camera = Camera.objects.create(cam_serial_num='IMG-100', user=self.user)

    def _make_chunk(self, user, chunk=0, type=StonesDetectionChunk.TYPE_COVERAGE):
        return StonesDetectionChunk.objects.create(
            user=user,
            date='2026-06-01',
            chunk=chunk,
            type=type,
            gcs_path=f'{user.username}/2026-06-01/{chunk}/{type}/',
            processing_start_date='2026-06-01T12:00:00Z',
            status=StonesDetectionChunk.STATUS_PROCESSING,
        )

    def _set_created_at(self, model, uuid, created_at):
        model.objects.filter(uuid=uuid).update(created_at=created_at)

    def _get(self, unit_id='IMG-100'):
        self.client.force_login(self.user)
        return self.client.get(reverse('unit_latest_image_url', args=[unit_id]))

    def test_unauthenticated_returns_403(self):
        response = self.client.get(reverse('unit_latest_image_url', args=['IMG-100']))
        self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)

    def test_foreign_unit_id_returns_404(self):
        other_user = User.objects.create_user(username='imageother', password='pass')
        Camera.objects.create(cam_serial_num='IMG-OTHER', user=other_user)
        response = self._get(unit_id='IMG-OTHER')
        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)

    def test_unknown_unit_id_returns_404(self):
        response = self._get(unit_id='DOES-NOT-EXIST')
        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)

    def test_no_coverage_rows_returns_404(self):
        response = self._get()
        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)
        self.assertIn('detail', response.data)

    def test_coverage_without_images_returns_404(self):
        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='img-cov-noimg', chunk=chunk, serial='IMG-100',
            captured_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            image_path=None,
        )
        response = self._get()
        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)

    @mock.patch('user.views._gcs_client')
    def test_falls_back_to_prediction_image_when_no_coverage_image(self, mock_gcs_client):
        mock_client = mock.MagicMock()
        mock_blob = mock.MagicMock()
        mock_blob.generate_signed_url.return_value = 'https://storage.googleapis.com/signed/image'
        mock_client.bucket.return_value.blob.return_value = mock_blob
        mock_gcs_client.return_value = mock_client

        chunk = self._make_chunk(self.user, type=StonesDetectionChunk.TYPE_PREDICTIONS)
        captured_at = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        EdgePrediction.objects.create(
            uuid='img-pred-1', chunk=chunk, serial='IMG-100',
            captured_at=captured_at, image_path='IMG-100/2026-06-01/img-pred-1.jpg',
        )

        response = self._get()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data['captured_at'], captured_at)
        mock_client.bucket.return_value.blob.assert_called_once_with('IMG-100/2026-06-01/img-pred-1.jpg')

    @mock.patch('user.views._gcs_client')
    def test_prefers_newer_prediction_image_over_older_coverage_image(self, mock_gcs_client):
        mock_client = mock.MagicMock()
        mock_blob = mock.MagicMock()
        mock_blob.generate_signed_url.return_value = 'https://storage.googleapis.com/signed/image'
        mock_client.bucket.return_value.blob.return_value = mock_blob
        mock_gcs_client.return_value = mock_client

        cov_chunk = self._make_chunk(self.user, chunk=0, type=StonesDetectionChunk.TYPE_COVERAGE)
        pred_chunk = self._make_chunk(self.user, chunk=1, type=StonesDetectionChunk.TYPE_PREDICTIONS)
        EdgeCoverage.objects.create(
            uuid='img-cov-older', chunk=cov_chunk, serial='IMG-100',
            captured_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc), image_path='old-cov.jpg',
        )
        EdgePrediction.objects.create(
            uuid='img-pred-newer', chunk=pred_chunk, serial='IMG-100',
            captured_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc), image_path='new-pred.jpg',
        )
        self._set_created_at(EdgeCoverage, 'img-cov-older', datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc))
        self._set_created_at(EdgePrediction, 'img-pred-newer', datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc))

        response = self._get()

        self.assertEqual(response.status_code, HTTP_200_OK)
        mock_client.bucket.return_value.blob.assert_called_once_with('new-pred.jpg')

    def test_coverage_from_reassigned_serial_is_not_used(self):
        # Same serial, but the chunk belongs to a different account
        other_user = User.objects.create_user(username='imageother2', password='pass')
        other_chunk = self._make_chunk(other_user, chunk=1)
        EdgeCoverage.objects.create(
            uuid='img-cov-leak', chunk=other_chunk, serial='IMG-100',
            captured_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            image_path='leak.jpg',
        )
        other_pred_chunk = self._make_chunk(other_user, chunk=2, type=StonesDetectionChunk.TYPE_PREDICTIONS)
        EdgePrediction.objects.create(
            uuid='img-pred-leak', chunk=other_pred_chunk, serial='IMG-100',
            captured_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            image_path='pred-leak.jpg',
        )
        response = self._get()
        self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)

    @mock.patch('user.views._gcs_client')
    def test_happy_path_returns_signed_url_and_captured_at(self, mock_gcs_client):
        mock_client = mock.MagicMock()
        mock_blob = mock.MagicMock()
        mock_blob.generate_signed_url.return_value = 'https://storage.googleapis.com/signed/image'
        mock_client.bucket.return_value.blob.return_value = mock_blob
        mock_gcs_client.return_value = mock_client

        chunk = self._make_chunk(self.user)
        captured_at = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        EdgeCoverage.objects.create(
            uuid='img-cov-1', chunk=chunk, serial='IMG-100',
            captured_at=captured_at, image_path='IMG-100/2026-06-01/img-cov-1.jpg',
        )

        response = self._get()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(response.data['url'], 'https://storage.googleapis.com/signed/image')
        self.assertEqual(response.data['captured_at'], captured_at)

        mock_client.bucket.assert_called_once_with('test-edge-bucket')
        mock_client.bucket.return_value.blob.assert_called_once_with('IMG-100/2026-06-01/img-cov-1.jpg')
        mock_blob.generate_signed_url.assert_called_once_with(
            expiration=timedelta(hours=1), method='GET', version='v4',
        )

    @mock.patch('user.views._gcs_client')
    def test_picks_most_recent_row_that_has_an_image(self, mock_gcs_client):
        mock_client = mock.MagicMock()
        mock_blob = mock.MagicMock()
        mock_blob.generate_signed_url.return_value = 'https://storage.googleapis.com/signed/image'
        mock_client.bucket.return_value.blob.return_value = mock_blob
        mock_gcs_client.return_value = mock_client

        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='img-cov-old', chunk=chunk, serial='IMG-100',
            captured_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
            image_path='old.jpg',
        )
        EdgeCoverage.objects.create(
            uuid='img-cov-new', chunk=chunk, serial='IMG-100',
            captured_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            image_path=None,
        )
        self._set_created_at(EdgeCoverage, 'img-cov-old', datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc))
        self._set_created_at(EdgeCoverage, 'img-cov-new', datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc))

        response = self._get()

        self.assertEqual(response.status_code, HTTP_200_OK)
        mock_client.bucket.return_value.blob.assert_called_once_with('old.jpg')

    @mock.patch('user.views._gcs_client')
    def test_gcs_exception_returns_400(self, mock_gcs_client):
        mock_gcs_client.side_effect = Exception("GCS error")

        chunk = self._make_chunk(self.user)
        EdgeCoverage.objects.create(
            uuid='img-cov-err', chunk=chunk, serial='IMG-100',
            captured_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            image_path='err.jpg',
        )

        response = self._get()

        self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)
