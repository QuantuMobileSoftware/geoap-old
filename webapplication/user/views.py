import logging
import os
import re
from collections import namedtuple
from datetime import datetime, timedelta
from allauth.account.views import ConfirmEmailView
from dj_rest_auth.registration.views import RegisterView as BasicRegisterView
from django.conf import settings
from django.contrib.auth.models import Group
from django.http import Http404
from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import status
from django.utils.translation import gettext_lazy as _
from rest_framework.generics import ListAPIView, ListCreateAPIView, UpdateAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK
from rest_framework.views import APIView
from dj_rest_auth.views import UserDetailsView

from devices.models import Camera
from user.models import EdgeCoverage, EdgePrediction, Transaction, User, UploadMissions
from aoi.models import Component, Request
from django.db.models import OuterRef, Q, Subquery
from user.serializers import TransactionSerializer, UnitSerializer, UnitTelemetrySerializer, UserSerializer, UploadMissionsSerializer
from user.stone_device_views import _gcs_client
from user.telemetry import BUCKET_MINUTES, build_unit_range_totals, build_unit_telemetry
from user.upload_utils import get_upload_config
from user.utils import day_window, rolling_window
from waffle import switch_is_active
from google.cloud import storage

logger = logging.getLogger(__name__)

DATA_VIDEO_FILENAME_RE = re.compile(
    r'^[A-Z0-9]+_UNIT\d{2}\d{14}_\d{4}\.MP4$',
    re.IGNORECASE,
)


class RegisterView(BasicRegisterView):
    def perform_create(self, serializer):
        user = super().perform_create(serializer)
        client_group = Group.objects.get(name="Client")
        user.groups.add(client_group)
        user.start_trial()
        return user


class CustomUserDetailsView(UserDetailsView):
    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        component_with_remote_executions = Component.objects.filter(Q(success=True) & Q(geoap_creds_required=True))
        response.data['server_for_calculation_is_needed'] = component_with_remote_executions.exists()
        if component_with_remote_executions.exists():
            server_is_overloaded_notification = switch_is_active('our_server_is_overloaded_notification')
            remote_server_available = switch_is_active('remote_server_available')
            if server_is_overloaded_notification:
                response.data['remote_server_available'] = False
            else:
                response.data['remote_server_available'] = remote_server_available
        return response


class VerifyEmailView(APIView, ConfirmEmailView):
    permission_classes = (AllowAny,)
    allowed_methods = ('GET', 'OPTIONS', 'HEAD')

    def verify_email(self):
        confirmation = self.get_object()
        confirmation.confirm(self.request)

    def get(self, *args, **kwargs):
        try:
            self.verify_email()
        except Http404:
            raise NotFound(_("Email verification failed"))
        return Response(data=_("Email has been successfully confirmed!"), status=HTTP_200_OK)


class TransactionPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class TransactionListAPIView(ListAPIView):
    permission_classes = (IsAuthenticated, )
    queryset = Transaction.objects.all()
    serializer_class = TransactionSerializer
    pagination_class = TransactionPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.has_perm("user.view_all_transactions"):
            queryset = queryset.filter(user=self.request.user)
        month = self.request.query_params.get('month')
        year = self.request.query_params.get('year')
        if month and year:
            queryset = queryset.filter(created_at__month=month, created_at__year=year)
        return queryset


class GoogleBucketFolderAPIView(APIView):
    permission_classes = (IsAuthenticated, )

    def get(self, request, *args, **kwargs):
        google_bucket_folder_path = self.request.user.stone_google_folder
        if not google_bucket_folder_path:
            return Response(status=status.HTTP_404_NOT_FOUND)

        try:
            storage_client = storage.Client.from_service_account_json(
                os.path.join(settings.PERSISTENT_STORAGE_PATH,
                             settings.OPERATIONS_SERVICE_CREDS))
            bucket = storage_client.bucket(google_bucket_folder_path)
            if not bucket.exists():
                return Response(
                    {"detail": "Storage bucket not found. Please check the bucket name in your account settings."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            user_prefix = f"{self.request.user.username}/"
            blobs = storage_client.list_blobs(google_bucket_folder_path, prefix=user_prefix)
            paths = [blob.name for blob in blobs]
        except Exception as e:
            logger.exception(
                "GCS error listing bucket folders for user=%s, bucket=%s: %s",
                request.user.id, google_bucket_folder_path, e,
            )
            return Response(
                {"detail": "Storage bucket is not available. Please check the bucket name in your account settings."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = []
        for path in paths:
            parts = path.rstrip('/').split('/')
            # Collect folder paths up to the session level (username/year/session/)
            for depth in range(2, min(4, len(parts))):
                folder_path = '/'.join(parts[:depth]) + '/'
                if folder_path not in results:
                    results.append(folder_path)

        if results:
            return Response(results)
        else:
            return Response(status=status.HTTP_204_NO_CONTENT)


class GenerateResumableUploadURLAPIView(APIView):
    """
    Generate a GCS resumable upload session URL for uploading a file into the stones_storage bucket.
    Accepts: GET method.

    Required query params:
        'file_name'   — name of the file to upload
        'file_type'   — MIME type of the file (e.g. video/mp4)
        'upload_type' — one of: 'data_video', 'calibration_video', 'log'
    Optional query params:
        'session_folder' — datetime-named folder from a previous call in the same session;
                           if omitted a new folder is generated (YYYY-MM-DD_HH-MM-SS).

    GCS layout:
        stones_storage/<user_folder>/<session_folder>/DCIM/<file>          (data_video)
        stones_storage/<user_folder>/<session_folder>/GPS_LOG/<file>       (log)
        stones_storage/<user_folder>/<session_folder>/<file>               (calibration_video)

    Returns: {'upload_url': ..., 'session_folder': ...}
    """
    permission_classes = (IsAuthenticated,)
    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):
        if not request.user.stone_google_folder:
            return Response(
                {"detail": "Upload bucket is not configured for this account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_folder = request.user.username

        file_name = request.query_params.get("file_name")
        file_type = request.query_params.get("file_type")
        upload_type = request.query_params.get("upload_type")
        session_folder = request.query_params.get("session_folder")

        if not file_name or not file_type or not upload_type:
            return Response(
                {"detail": "file_name, file_type, and upload_type query parameters are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        mission = UploadMissions.objects.filter(
            user=request.user, gcs_path=session_folder
        ).select_related('component').first() if session_folder else None
        component = (mission and mission.component) or request.user.default_upload_component

        try:
            upload_cfg = get_upload_config(component)
        except ValueError as e:
            logger.warning(
                "Invalid upload configuration for user=%s, component=%s: %s",
                getattr(request.user, "id", None),
                getattr(component, "id", None) if component is not None else None,
                e,
            )
            return Response(
                {"detail": _("Upload configuration is invalid for this account.")},
                status=status.HTTP_400_BAD_REQUEST,
            )
        upload_folders = upload_cfg['upload']
        unit_folder = upload_cfg['unit_folder']

        if upload_type not in upload_folders:
            return Response(
                {"detail": f"upload_type must be one of: {', '.join(upload_folders)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if upload_type == 'data_video' and not DATA_VIDEO_FILENAME_RE.match(file_name):
            return Response(
                {"detail": "data_video file name must match the format: PREFIX_UNITnn{YYYYMMDD}{HHMMSS}_ssss.MP4 (e.g. 00SAIRS_UNIT0120251028071253_0010.MP4)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if upload_type == 'calibration_video':
            ext = os.path.splitext(file_name)[1]
            file_name = f'calibration{ext}'

        if mission:
            existing_names = {f['name'] for f in (mission.uploaded_files or [])}
            if file_name in existing_names:
                return Response(
                    {'detail': f"File '{file_name}' has already been uploaded to this session."},
                    status=status.HTTP_409_CONFLICT,
                )

        if not session_folder:
            now = datetime.now()
            session_folder = f"{now.strftime('%Y')}/{now.strftime('%Y-%m-%d_%H-%M-%S')}"

        type_folder = upload_folders[upload_type]
        if type_folder:
            blob_path = os.path.join(user_folder, session_folder, unit_folder, type_folder, file_name)
        else:
            blob_path = os.path.join(user_folder, session_folder, unit_folder, file_name)

        try:
            storage_client = storage.Client.from_service_account_json(
                os.path.join(settings.PERSISTENT_STORAGE_PATH, settings.OPERATIONS_SERVICE_CREDS)
            )
            bucket = storage_client.bucket(request.user.stone_google_folder)
            blob = bucket.blob(blob_path)
            resumable_url = blob.create_resumable_upload_session(
                content_type=file_type,
                origin=getattr(settings, "GOOGLE_CLOUD_UPLOAD_ORIGIN", None),
            )
        except Exception as e:
            logger.exception(
                "GCS error generating upload URL for user=%s, bucket=%s: %s",
                request.user.id, request.user.stone_google_folder, e,
            )
            return Response(
                {"detail": "Storage bucket is not available. Please check the bucket name in your account settings."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        logger.info(
            f"Resumable URL generated for user={request.user.id}, upload_type={upload_type}, file={blob_path}"
        )
        return Response(
            {"upload_url": resumable_url, "session_folder": session_folder},
            status=status.HTTP_200_OK,
        )


class GenerateDownloadURLAPIView(APIView):
    """
    Generate a short-lived GCS signed download URL for a previously uploaded file.
    Accepts: GET method.

    Required query params:
        'file_name'      — name of the file
        'upload_type'    — one of: 'data_video', 'calibration_video', 'log'
        'session_folder' — the gcs_path value stored on the mission (e.g. '2024/2024-01-01_12-00-00')

    Returns: {'download_url': ...}
    """
    permission_classes = (IsAuthenticated,)
    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):
        if not request.user.stone_google_folder:
            return Response(
                {"detail": "Upload bucket is not configured for this account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        file_name = request.query_params.get("file_name")
        upload_type = request.query_params.get("upload_type")
        session_folder = request.query_params.get("session_folder")

        if not file_name or not upload_type or not session_folder:
            return Response(
                {"detail": "file_name, upload_type, and session_folder are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        mission = UploadMissions.objects.filter(
            user=request.user, gcs_path=session_folder
        ).select_related('component').first()
        component = (mission and mission.component) or request.user.default_upload_component

        try:
            upload_cfg = get_upload_config(component)
        except ValueError as e:
            logger.exception("Failed to get upload config for component %s", component)
            return Response(
                {"detail": _("Invalid upload configuration.")},
                status=status.HTTP_400_BAD_REQUEST,
            )
        upload_folders = upload_cfg['upload']
        unit_folder = upload_cfg['unit_folder']

        if upload_type not in upload_folders:
            return Response(
                {"detail": f"upload_type must be one of: {', '.join(upload_folders)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_folder = request.user.username
        type_folder = upload_folders[upload_type]
        if type_folder:
            blob_path = os.path.join(user_folder, session_folder, unit_folder, type_folder, file_name)
        else:
            blob_path = os.path.join(user_folder, session_folder, unit_folder, file_name)

        try:
            storage_client = storage.Client.from_service_account_json(
                os.path.join(settings.PERSISTENT_STORAGE_PATH, settings.OPERATIONS_SERVICE_CREDS)
            )
            bucket = storage_client.bucket(request.user.stone_google_folder)
            blob = bucket.blob(blob_path)
            download_url = blob.generate_signed_url(
                expiration=timedelta(hours=1),
                method="GET",
                version="v4",
            )
        except Exception as e:
            logger.exception(
                "GCS error generating download URL for user=%s, bucket=%s: %s",
                request.user.id, request.user.stone_google_folder, e,
            )
            return Response(
                {"detail": "Storage bucket is not available. Please check the bucket name in your account settings."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        logger.info(
            f"Download URL generated for user={request.user.id}, upload_type={upload_type}, file={blob_path}"
        )
        return Response({"download_url": download_url}, status=status.HTTP_200_OK)


class UploadMissionsListCreateAPIView(ListCreateAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = UploadMissionsSerializer
    pagination_class = None

    def get_queryset(self):
        return UploadMissions.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        now = datetime.now()
        session_folder = now.strftime("%Y-%m-%d_%H-%M-%S")
        year = now.strftime("%Y")
        gcs_path = f"{year}/{session_folder}"
        component = serializer.validated_data.get('component') or self.request.user.default_upload_component
        serializer.save(
            user=self.request.user,
            status=UploadMissions.STATUS_IN_PROGRESS,
            gcs_path=gcs_path,
            component=component,
        )


class UploadMissionsUpdateAPIView(UpdateAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = UploadMissionsSerializer
    http_method_names = ['patch']

    def get_queryset(self):
        return UploadMissions.objects.filter(user=self.request.user)

    def perform_update(self, serializer):
        instance = self.get_object()
        new_status = serializer.validated_data.get('status')
        if new_status == UploadMissions.STATUS_FAILED and instance.status == UploadMissions.STATUS_COMPLETED:
            raise ValidationError('Cannot mark a completed upload as failed.')
        instance = serializer.save()
        if (
            instance.status == UploadMissions.STATUS_COMPLETED
            and instance.component
            and self.request.user.stone_google_folder
            and not instance.trajectory_request_id
        ):
            full_gcs_path = (
                f"{self.request.user.stone_google_folder}"
                f"/{self.request.user.username}"
                f"/{instance.gcs_path}/"
            )
            trajectory_request = Request.objects.create(
                user=self.request.user,
                component=instance.component,
                aoi=None,
                polygon=None,
                additional_parameter=full_gcs_path,
            )
            instance.trajectory_request = trajectory_request
            instance.save(update_fields=['trajectory_request'])


class UploadMissionsDeleteAPIView(APIView):
    """Delete a failed mission and remove its GCS folder contents."""
    permission_classes = (IsAuthenticated,)

    def delete(self, request, pk, *args, **kwargs):
        try:
            mission = UploadMissions.objects.get(pk=pk, user=request.user)
        except UploadMissions.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if mission.status != UploadMissions.STATUS_FAILED:
            return Response(
                {"detail": "Only failed missions can be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if request.user.stone_google_folder and mission.gcs_path:
            try:
                storage_client = storage.Client.from_service_account_json(
                    os.path.join(settings.PERSISTENT_STORAGE_PATH, settings.OPERATIONS_SERVICE_CREDS)
                )
                bucket = storage_client.bucket(request.user.stone_google_folder)
                prefix = f"{request.user.username}/{mission.gcs_path}/"
                blobs = list(storage_client.list_blobs(request.user.stone_google_folder, prefix=prefix))
                if blobs:
                    bucket.delete_blobs(blobs, on_error=lambda blob: None)
            except Exception as e:
                logger.exception(
                    "GCS error deleting folder for mission=%s, user=%s: %s",
                    mission.id, request.user.id, e,
                )

        mission.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UploadMissionsRemoveFilesAPIView(APIView):
    """Remove specific files from a completed mission and re-run trajectory."""
    permission_classes = (IsAuthenticated,)

    def post(self, request, pk, *args, **kwargs):
        try:
            mission = UploadMissions.objects.select_related(
                'component', 'trajectory_request'
            ).get(pk=pk, user=request.user)
        except UploadMissions.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if mission.status != UploadMissions.STATUS_COMPLETED:
            return Response(
                {"detail": "Files can only be removed from completed missions."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        files_to_remove = request.data.get('files_to_remove', [])
        if not files_to_remove or not isinstance(files_to_remove, list):
            return Response(
                {"detail": "files_to_remove must be a non-empty list of file names."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        component = mission.component or request.user.default_upload_component
        try:
            upload_cfg = get_upload_config(component)
        except ValueError as e:
            logger.warning(
                "Invalid upload config for mission=%s, user=%s: %s",
                mission.id, request.user.id, e,
            )
            return Response(
                {"detail": "Upload configuration is invalid for this account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        upload_folders = upload_cfg['upload']
        unit_folder = upload_cfg['unit_folder']
        user_folder = request.user.username
        uploaded_files = mission.uploaded_files or []
        file_map = {f['name']: f for f in uploaded_files}

        if request.user.stone_google_folder:
            try:
                storage_client = storage.Client.from_service_account_json(
                    os.path.join(settings.PERSISTENT_STORAGE_PATH, settings.OPERATIONS_SERVICE_CREDS)
                )
                bucket = storage_client.bucket(request.user.stone_google_folder)
                blobs_to_delete = []
                for file_name in files_to_remove:
                    file_record = file_map.get(file_name)
                    if not file_record:
                        continue
                    upload_type = file_record.get('type')
                    type_folder = upload_folders.get(upload_type)
                    if type_folder:
                        blob_path = os.path.join(
                            user_folder, mission.gcs_path, unit_folder, type_folder, file_name
                        )
                    else:
                        blob_path = os.path.join(
                            user_folder, mission.gcs_path, unit_folder, file_name
                        )
                    blobs_to_delete.append(bucket.blob(blob_path))
                if blobs_to_delete:
                    bucket.delete_blobs(blobs_to_delete, on_error=lambda blob: None)
            except Exception as e:
                logger.exception(
                    "GCS error removing files for mission=%s, user=%s: %s",
                    mission.id, request.user.id, e,
                )
                return Response(
                    {"detail": "Failed to delete files from storage."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        remove_set = set(files_to_remove)
        mission.uploaded_files = [f for f in uploaded_files if f['name'] not in remove_set]

        remaining_videos = [f for f in mission.uploaded_files if f.get('type') == 'data_video']

        mission.trajectory_request = None
        mission.save(update_fields=['uploaded_files', 'trajectory_request'])

        if not remaining_videos:
            data = UploadMissionsSerializer(mission).data
            data['suggest_delete'] = True
            return Response(data, status=status.HTTP_200_OK)

        if component and request.user.stone_google_folder:
            full_gcs_path = (
                f"{request.user.stone_google_folder}"
                f"/{request.user.username}"
                f"/{mission.gcs_path}/"
            )
            trajectory_request = Request.objects.create(
                user=request.user,
                component=component,
                aoi=None,
                polygon=None,
                additional_parameter=full_gcs_path,
            )
            mission.trajectory_request = trajectory_request
            mission.save(update_fields=['trajectory_request'])

        serializer = UploadMissionsSerializer(mission)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UploadMissionsRerunTrajectoryAPIView(APIView):
    """Re-run trajectory processing for a completed mission with a failed trajectory."""
    permission_classes = (IsAuthenticated,)

    def post(self, request, pk, *args, **kwargs):
        try:
            mission = UploadMissions.objects.select_related(
                'component', 'trajectory_request'
            ).get(pk=pk, user=request.user)
        except UploadMissions.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if mission.status != UploadMissions.STATUS_COMPLETED:
            return Response(
                {"detail": "Only completed missions can have their trajectory re-run."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        req = mission.trajectory_request
        trajectory_failed = req and (req.error or (req.finished_at and not req.success))
        if not trajectory_failed:
            return Response(
                {"detail": "Trajectory has not failed; re-run is not needed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        component = mission.component or request.user.default_upload_component
        if not component or not request.user.stone_google_folder:
            return Response(
                {"detail": "Component or storage bucket is not configured for this account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        full_gcs_path = (
            f"{request.user.stone_google_folder}"
            f"/{request.user.username}"
            f"/{mission.gcs_path}/"
        )
        new_request = Request.objects.create(
            user=request.user,
            component=component,
            aoi=None,
            polygon=None,
            additional_parameter=full_gcs_path,
        )
        mission.trajectory_request = new_request
        mission.save(update_fields=['trajectory_request'])

        return Response(UploadMissionsSerializer(mission).data, status=status.HTTP_200_OK)


UnitRow = namedtuple('UnitRow', [
'unit_id', 'machine_label', 'last_received_at', 'last_captured_at', 'lat', 'lng', 'has_recent_image',
])


def _build_units(user):
    latest_uuid_subquery = (
        EdgeCoverage.objects
        .filter(
            serial=OuterRef('cam_serial_num'),
            chunk__user_id=OuterRef('user_id'),
            chunk__user=user,
        )
        .order_by('-created_at')
        .values('uuid')[:1]
    )

    cameras = list(
        Camera.objects
        .filter(user=user)
        .annotate(latest_coverage_uuid=Subquery(latest_uuid_subquery))
        .order_by('cam_serial_num')
    )

    latest_uuids = [c.latest_coverage_uuid for c in cameras if c.latest_coverage_uuid]
    coverage_by_uuid = {
        cov.uuid: cov for cov in EdgeCoverage.objects.filter(uuid__in=latest_uuids)
    }

    rows = []
    for cam in cameras:
        cov = coverage_by_uuid.get(cam.latest_coverage_uuid)
        rows.append(UnitRow(
            unit_id=cam.cam_serial_num,
            machine_label=cam.cam_serial_num,
            last_received_at=cov.created_at if cov else None,
            last_captured_at=cov.captured_at if cov else None,
            lat=cov.location.y if (cov and cov.location) else None,
            lng=cov.location.x if (cov and cov.location) else None,
            has_recent_image=(cov.image_path is not None) if cov else None,
        ))
    return rows


class UnitListAPIView(APIView):
    permission_classes = (IsAuthenticated, )

    def get(self, request, *args, **kwargs):
        return Response({
            'timezone': request.user.timezone,
            'server_time': dj_timezone.now(),
            'units': UnitSerializer(_build_units(request.user), many=True).data,
        })


TRUTHY_VALUES = {'true', '1'}


class UnitTelemetryAPIView(APIView):
    permission_classes = (IsAuthenticated, )

    def get(self, request, *args, **kwargs):
        day_param = request.query_params.get('day')
        rolling_param = request.query_params.get('rolling')

        if bool(day_param) == bool(rolling_param):
            return Response(
                {'detail': "Exactly one of 'day' or 'rolling' query params is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if day_param:
            try:
                parsed_date = parse_date(day_param)
            except ValueError:
                parsed_date = None
            if parsed_date is None:
                return Response(
                    {'detail': "'day' must be in YYYY-MM-DD format."}, status=status.HTTP_400_BAD_REQUEST,
                )
            start, end = day_window(parsed_date, request.user.timezone)
        else:
            if rolling_param.lower() not in TRUTHY_VALUES:
                return Response(
                    {'detail': "'rolling' must be a truthy value ('true' or '1')."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            start, end = rolling_window()

        range_from_param = request.query_params.get('range_from')
        range_to_param = request.query_params.get('range_to')

        if bool(range_from_param) != bool(range_to_param):
            return Response(
                {'detail': "'range_from' and 'range_to' must be provided together."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        range_start, range_end = None, None
        if range_from_param:
            range_start = parse_datetime(range_from_param)
            range_end = parse_datetime(range_to_param)
            if range_start is None or range_end is None or dj_timezone.is_naive(range_start) \
                    or dj_timezone.is_naive(range_end):
                return Response(
                    {'detail': "'range_from' and 'range_to' must be timezone-aware ISO 8601 datetimes."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if range_start >= range_end or range_start < start or range_end > end:
                return Response(
                    {'detail': "'range_from'/'range_to' must be a non-empty sub-range within the resolved window."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        latest_coverage_subquery = (
            EdgeCoverage.objects
            .filter(serial=OuterRef('cam_serial_num'), chunk__user=request.user)
            .order_by('-created_at')
            .values('created_at')[:1]
        )
        cameras = (
            Camera.objects.filter(user=request.user)
            .annotate(latest_coverage_created_at=Subquery(latest_coverage_subquery))
            .order_by('cam_serial_num')
        )

        unit_id = request.query_params.get('unit_id')
        if unit_id:
            cameras = cameras.filter(cam_serial_num=unit_id)
            if not cameras.exists():
                raise Http404

        cameras = list(cameras)
        now = dj_timezone.now()
        units = [
            build_unit_telemetry(camera, request.user, start, end, camera.latest_coverage_created_at, now)
            for camera in cameras
        ]

        if range_start is not None:
            for camera, unit in zip(cameras, units):
                unit['totals'] = build_unit_range_totals(camera, request.user, range_start, range_end)

        return Response({
            'timezone': request.user.timezone,
            'from': start,
            'to': end,
            'bucket_minutes': BUCKET_MINUTES,
            'units': UnitTelemetrySerializer(units, many=True).data,
        })


class UnitLatestImageURLAPIView(APIView):
    permission_classes = (IsAuthenticated, )

    def get(self, request, unit_id, *args, **kwargs):
        camera = Camera.objects.filter(user=request.user, cam_serial_num=unit_id).first()
        if camera is None:
            raise Http404

        candidates = []
        for model in (EdgeCoverage, EdgePrediction):
            row = (
                model.objects
                .filter(serial=unit_id, chunk__user=request.user, image_path__isnull=False)
                .order_by('-created_at')
                .values('image_path', 'captured_at', 'created_at')
                .first()
            )
            if row is not None:
                candidates.append(row)

        if not candidates:
            return Response(
                {'detail': "No image has been received for this unit yet."},
                status=status.HTTP_404_NOT_FOUND,
            )

        latest = max(candidates, key=lambda row: row['created_at'])
        captured_at = latest['captured_at'] or latest['created_at']

        try:
            client = _gcs_client()
            bucket = client.bucket(request.user.stones_storage_edge)
            url = bucket.blob(latest['image_path']).generate_signed_url(
                expiration=timedelta(hours=1),
                method="GET",
                version="v4",
            )
        except Exception as error:
            logger.exception(
                "GCS error generating latest-image URL for user=%s, unit=%s: %s",
                request.user.id, unit_id, error,
            )
            return Response(
                {'detail': "Storage bucket is not available. Please check the bucket name in your account settings."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info(f"Latest-image URL generated for user={request.user.id}, unit={unit_id}")
        return Response({'url': url, 'captured_at': captured_at})
