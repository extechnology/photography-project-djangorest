import os
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, FileUploadParser
from django.conf import settings
from django.http import FileResponse, HttpResponse, Http404
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired

from App.Storage.services.resumable_upload_service import ResumableUploadService
from App.Storage.services.storage_service import get_storage_provider, LocalStorageProvider


class ResumableUploadInitView(APIView):
    """
    POST /api/storage/uploads/init/
    Initializes a new chunked resumable upload session.
    Validates storage quotas and reserves upload space.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        filename = request.data.get("filename") or request.data.get("name")
        total_size = request.data.get("total_size") or request.data.get("size") or request.data.get("file_size")
        target_type = request.data.get("target_type", "gallery").lower()
        target_id = (
            request.data.get("target_id")
            or request.data.get("gallery_id")
            or request.data.get("session_id")
            or request.data.get("event_id")
        )
        chunk_size = request.data.get("chunk_size", 8 * 1024 * 1024)  # 8 MB default

        if not filename or total_size is None:
            return Response(
                {"error": "Both 'filename' and 'total_size' are required.", "code": "INVALID_PARAMETERS"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            total_size = int(total_size)
            chunk_size = int(chunk_size)
        except (ValueError, TypeError):
            return Response(
                {"error": "'total_size' and 'chunk_size' must be integers.", "code": "INVALID_PARAMETERS"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        extra_data = {
            "section_title": request.data.get("section_title", "HIGHLIGHTS"),
            "category": request.data.get("category"),
        }

        try:
            res = ResumableUploadService.init_upload(
                user=request.user,
                filename=filename,
                total_size=total_size,
                target_type=target_type,
                target_id=target_id,
                chunk_size=chunk_size,
                extra_data=extra_data,
            )
            return Response(res, status=status.HTTP_201_CREATED)
        except PermissionError as pe:
            return Response(
                {"error": str(pe), "code": "STORAGE_LIMIT_EXCEEDED"},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        except Exception as e:
            return Response(
                {"error": str(e), "code": "INIT_FAILED"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class ResumableUploadChunkView(APIView):
    """
    POST/PUT /api/storage/uploads/<str:upload_id>/chunk/ or /api/storage/uploads/chunk/
    Uploads a single chunk of a file. Streams directly to disk.
    Accepts chunk file under 'chunk', 'file', or raw request body.
    Supports 'Upload-Offset' or 'chunk_index' parameters.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, FileUploadParser]

    def put(self, request, upload_id=None):
        upload_id = upload_id or request.data.get("upload_id") or request.query_params.get("upload_id")
        if not upload_id:
            return Response(
                {"error": "'upload_id' is required.", "code": "MISSING_UPLOAD_ID"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        chunk_file = request.FILES.get("chunk") or request.FILES.get("file")
        if not chunk_file:
            # Fallback to raw body if sent directly
            if hasattr(request, "data") and isinstance(request.data, dict) and "file" in request.data:
                chunk_file = request.data["file"]
            elif hasattr(request, "_request"):
                chunk_file = request._request

        if not chunk_file:
            return Response(
                {"error": "No chunk data provided.", "code": "MISSING_CHUNK"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        chunk_index = request.data.get("chunk_index")
        if chunk_index is not None:
            try:
                chunk_index = int(chunk_index)
            except ValueError:
                chunk_index = None

        offset = request.headers.get("Upload-Offset") or request.data.get("offset")
        if offset is not None:
            try:
                offset = int(offset)
            except ValueError:
                offset = None

        try:
            res = ResumableUploadService.append_chunk(
                upload_id=upload_id,
                user=request.user,
                chunk_file=chunk_file,
                chunk_index=chunk_index,
                offset=offset,
            )
            return Response(res, status=status.HTTP_200_OK)
        except PermissionError as pe:
            return Response({"error": str(pe), "code": "FORBIDDEN"}, status=status.HTTP_403_FORBIDDEN)
        except FileNotFoundError:
            return Response({"error": "Upload session not found.", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e), "code": "CHUNK_FAILED"}, status=status.HTTP_400_BAD_REQUEST)

    def post(self, request, upload_id=None):
        return self.put(request, upload_id=upload_id)


class ResumableUploadStatusView(APIView):
    """
    GET /api/storage/uploads/<str:upload_id>/status/ or /api/storage/uploads/status/?upload_id=...
    Returns current offset, chunks received, and total progress for resuming.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, upload_id=None):
        upload_id = upload_id or request.query_params.get("upload_id") or request.data.get("upload_id")
        if not upload_id:
            return Response(
                {"error": "'upload_id' is required.", "code": "MISSING_UPLOAD_ID"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            res = ResumableUploadService.get_status(upload_id=upload_id, user=request.user)
            return Response(res, status=status.HTTP_200_OK)
        except PermissionError as pe:
            return Response({"error": str(pe), "code": "FORBIDDEN"}, status=status.HTTP_403_FORBIDDEN)
        except FileNotFoundError:
            return Response({"error": "Upload session not found.", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)


class ResumableUploadCompleteView(APIView):
    """
    POST /api/storage/uploads/<str:upload_id>/complete/ or /api/storage/uploads/complete/
    Finalizes upload, verifies size, creates database records, dispatches background processing.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, upload_id=None):
        upload_id = upload_id or request.data.get("upload_id") or request.query_params.get("upload_id")
        if not upload_id:
            return Response(
                {"error": "'upload_id' is required.", "code": "MISSING_UPLOAD_ID"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            res = ResumableUploadService.complete_upload(
                upload_id=upload_id,
                user=request.user,
                request=request,
            )
            return Response(res, status=status.HTTP_201_CREATED)
        except PermissionError as pe:
            return Response({"error": str(pe), "code": "FORBIDDEN"}, status=status.HTTP_403_FORBIDDEN)
        except FileNotFoundError:
            return Response({"error": "Upload session not found.", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e), "code": "COMPLETION_FAILED"}, status=status.HTTP_400_BAD_REQUEST)


class ResumableUploadCancelView(APIView):
    """
    DELETE/POST /api/storage/uploads/<str:upload_id>/cancel/ or /api/storage/uploads/cancel/
    Cancels upload session, cleans up temporary chunks on disk, releases quota reservations.
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, upload_id=None):
        upload_id = upload_id or request.data.get("upload_id") or request.query_params.get("upload_id")
        if not upload_id:
            return Response(
                {"error": "'upload_id' is required.", "code": "MISSING_UPLOAD_ID"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            res = ResumableUploadService.cancel_upload(upload_id=upload_id, user=request.user)
            return Response(res, status=status.HTTP_200_OK)
        except PermissionError as pe:
            return Response({"error": str(pe), "code": "FORBIDDEN"}, status=status.HTTP_403_FORBIDDEN)
        except FileNotFoundError:
            return Response({"error": "Upload session not found.", "code": "NOT_FOUND"}, status=status.HTTP_404_NOT_FOUND)

    def post(self, request, upload_id=None):
        return self.delete(request, upload_id=upload_id)


class DirectUploadExecuteView(APIView):
    """
    PUT/POST /api/storage/direct-upload/?token=...&key=...
    Receives direct binary stream for pre-signed local upload URLs.
    Validates cryptographic signature and streams file directly to disk.
    """
    permission_classes = []  # Token or user authenticated
    parser_classes = [MultiPartParser, FormParser, FileUploadParser]

    def put(self, request):
        signer = TimestampSigner()
        token = request.query_params.get("token") or request.data.get("token")
        key = request.query_params.get("key") or request.data.get("key")
        if not key:
            return Response({"error": "Query parameter 'key' is required."}, status=status.HTTP_400_BAD_REQUEST)

        if token:
            try:
                expected_payload = f"{key}:upload"
                valid_payload = signer.unsign(token, max_age=3600)
                if valid_payload != expected_payload:
                    return Response({"error": "Invalid upload signature."}, status=status.HTTP_403_FORBIDDEN)
            except SignatureExpired:
                return Response({"error": "Upload token has expired."}, status=status.HTTP_403_FORBIDDEN)
            except BadSignature:
                return Response({"error": "Tampered or invalid signature."}, status=status.HTTP_403_FORBIDDEN)
        elif not (request.user and request.user.is_authenticated):
            return Response({"error": "Valid token or authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        storage = get_storage_provider()
        content_type = request.content_type or "application/octet-stream"
        file_obj = request.FILES.get("file") if hasattr(request, "FILES") else None

        if file_obj:
            if hasattr(storage, "save_file"):
                storage.save_file(key, file_obj, content_type=content_type)
            else:
                storage.upload(key, file_obj.read(), content_type=content_type)
        elif hasattr(storage, "save_file"):
            storage.save_file(key, request._request, content_type=content_type)
        else:
            storage.upload(key, request.body, content_type=content_type)

        meta = storage.get_metadata(key)
        return Response({
            "status": "success",
            "message": "File streamed successfully to storage.",
            "storage_key": key,
            "size": meta.get("size", 0),
        }, status=status.HTTP_200_OK)

    def post(self, request):
        return self.put(request)


class DirectMediaFileServeView(APIView):
    """
    GET /api/storage/media-file/?token=...&key=...
    Securely serves files referenced by signed download URLs.
    Employs Nginx X-Accel-Redirect when enabled, or chunked FileResponse fallback.
    """
    permission_classes = []  # Token or user authorized

    def get(self, request):
        signer = TimestampSigner()
        token = request.query_params.get("token")
        key = request.query_params.get("key")
        if not key:
            raise Http404("Missing key.")

        filename = os.path.basename(key)
        if token:
            try:
                valid_payload = signer.unsign(token, max_age=3600)
                if not valid_payload.startswith(f"{key}:"):
                    return Response({"error": "Invalid token signature."}, status=status.HTTP_403_FORBIDDEN)
                filename = valid_payload.split(":", 1)[1] or os.path.basename(key)
            except (SignatureExpired, BadSignature):
                return Response({"error": "Signature expired or invalid."}, status=status.HTTP_403_FORBIDDEN)
        elif not (request.user and request.user.is_authenticated):
            return Response({"error": "Valid token or authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        storage = get_storage_provider()
        if not storage.exists(key):
            raise Http404("File not found.")

        use_x_accel = getattr(settings, 'USE_X_ACCEL_REDIRECT', False) or request.headers.get('X-Accel-Support') == 'true'
        clean_key = key.lstrip("/").replace("\\", "/")

        if use_x_accel and isinstance(storage, LocalStorageProvider):
            response = HttpResponse()
            response['X-Accel-Redirect'] = f"/protected_media/storage_objects/{clean_key}"
            response['Content-Type'] = 'application/octet-stream'
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

        if isinstance(storage, LocalStorageProvider):
            abs_p = storage.get_absolute_path(key)
            return FileResponse(open(abs_p, "rb"), as_attachment=True, filename=filename)

        return FileResponse(storage.open_stream(key), as_attachment=True, filename=filename)
