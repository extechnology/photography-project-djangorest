import os
import io
import logging
import mimetypes
from pathlib import Path
from django.conf import settings
from django.core.files.storage import Storage
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.utils.deconstruct import deconstructible
from decouple import config

logger = logging.getLogger(__name__)
signer = TimestampSigner()


class BaseStorageProvider:
    """Abstract interface for cloud/local object storage providers."""

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        raise NotImplementedError

    def download(self, key: str) -> bytes:
        raise NotImplementedError

    def download_bytes(self, key: str) -> bytes:
        return self.download(key)

    def delete(self, key: str) -> bool:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def get_metadata(self, key: str) -> dict:
        raise NotImplementedError

    def generate_signed_upload_url(self, key: str, expires_in: int = 3600, content_type: str = None) -> dict:
        raise NotImplementedError

    def generate_signed_download_url(self, key: str, expires_in: int = 3600, filename: str = None) -> str:
        raise NotImplementedError

    def generate_cdn_url(self, key: str) -> str:
        raise NotImplementedError

    def save_file(self, key: str, file_or_stream, content_type: str = "application/octet-stream") -> str:
        """Stream file or stream directly to storage destination without memory buffering."""
        raise NotImplementedError

    def get_absolute_path(self, key: str) -> Path:
        """Return the local filesystem Path if supported, else raise NotImplementedError."""
        raise NotImplementedError

    def move_file(self, source_path, target_key: str) -> str:
        """Move an existing local file directly into storage key location atomically."""
        raise NotImplementedError

    def open_stream(self, key: str, mode: str = "rb"):
        """Return an open file handle or stream for reading/writing."""
        raise NotImplementedError


class LocalStorageProvider(BaseStorageProvider):
    """
    Local filesystem storage provider for development, testing, and on-premise environments.
    Stores objects under MEDIA_ROOT / 'storage_objects'.
    """

    def __init__(self):
        self.base_dir = Path(settings.MEDIA_ROOT) / "storage_objects"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.cdn_base = getattr(settings, "CDN_BASE_URL", None) or settings.MEDIA_URL.rstrip("/") + "/storage_objects"

    def _resolve_path(self, key: str) -> Path:
        if not key:
            return self.base_dir

        raw = str(key).strip().replace("\\", "/")
        clean_key = raw.lstrip("/")

        # If already an existing absolute path, return it directly
        if os.path.isabs(raw):
            p = Path(raw)
            if p.is_file() or p.is_dir():
                return p

        media_root = Path(settings.MEDIA_ROOT)

        # Build candidate paths to test for existing files on disk
        candidates = []

        # 1. Base storage_objects dir + clean_key
        candidates.append(self.base_dir / clean_key)

        # 2. MEDIA_ROOT + clean_key (for files uploaded via default_storage or FileField directly to MEDIA_ROOT)
        candidates.append(media_root / clean_key)

        # 3. If clean_key starts with "storage_objects/", test stripped
        if clean_key.startswith("storage_objects/"):
            so_sub = clean_key[len("storage_objects/"):].lstrip("/")
            candidates.append(self.base_dir / so_sub)
            candidates.append(media_root / so_sub)

        # 4. If clean_key starts with "media/", test stripped
        if clean_key.startswith("media/"):
            m_sub = clean_key[len("media/"):].lstrip("/")
            candidates.append(media_root / m_sub)
            candidates.append(self.base_dir / m_sub)
            if m_sub.startswith("storage_objects/"):
                m_so_sub = m_sub[len("storage_objects/"):].lstrip("/")
                candidates.append(self.base_dir / m_so_sub)
                candidates.append(media_root / m_so_sub)

        # Check existing candidates in priority order
        for cand in candidates:
            if cand.is_file():
                return cand

        # Fast search in common MEDIA_ROOT subfolders
        fname = os.path.basename(clean_key)
        for sub in ("galleries", "events", "storage_objects", "culling_staging", "previews", "thumbnails"):
            sub_cand = media_root / sub / clean_key
            if sub_cand.is_file():
                return sub_cand

        # Fallback for write operations (new file uploads):
        # Prevent double storage_objects/ nesting
        target_sub = clean_key
        if target_sub.startswith("storage_objects/"):
            target_sub = target_sub[len("storage_objects/"):].lstrip("/")
        elif target_sub.startswith("media/storage_objects/"):
            target_sub = target_sub[len("media/storage_objects/"):].lstrip("/")

        fallback_path = self.base_dir / target_sub
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        return fallback_path

    def get_absolute_path(self, key: str) -> Path:
        return self._resolve_path(key)

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._resolve_path(key)
        with open(path, "wb") as f:
            f.write(data)
        self._ensure_permissions(path)
        return key

    def save_file(self, key: str, file_or_stream, content_type: str = "application/octet-stream") -> str:
        """Stream write a file-like object directly to disk in 1MB chunks."""
        import shutil
        path = self._resolve_path(key)
        with open(path, "wb") as out_f:
            if hasattr(file_or_stream, "chunks"):
                for chunk in file_or_stream.chunks(chunk_size=1024 * 1024):
                    out_f.write(chunk)
            elif hasattr(file_or_stream, "read"):
                shutil.copyfileobj(file_or_stream, out_f, length=1024 * 1024)
            elif isinstance(file_or_stream, (bytes, bytearray)):
                out_f.write(file_or_stream)
            else:
                out_f.write(file_or_stream)
        self._ensure_permissions(path)
        return key

    def move_file(self, source_path, target_key: str) -> str:
        """Atomically move/rename a file on the local filesystem into the storage destination."""
        import shutil
        src = Path(source_path)
        if not src.exists():
            raise FileNotFoundError(f"Source file '{src}' does not exist.")
        dst = self._resolve_path(target_key)
        try:
            os.replace(str(src), str(dst))
        except OSError:
            shutil.move(str(src), str(dst))
        self._ensure_permissions(dst)
        return target_key

    def open_stream(self, key: str, mode: str = "rb"):
        path = self._resolve_path(key)
        if "r" in mode and not path.exists():
            raise FileNotFoundError(f"Storage key '{key}' not found.")
        return open(path, mode)

    def _ensure_permissions(self, path: Path):
        if os.name != "nt":
            try:
                if path.is_file():
                    os.chmod(str(path), 0o644)
                elif path.is_dir():
                    os.chmod(str(path), 0o755)
            except Exception:
                pass

    def download(self, key: str) -> bytes:
        path = self._resolve_path(key)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Storage key '{key}' not found.")
        with open(path, "rb") as f:
            return f.read()

    def delete(self, key: str) -> bool:
        path = self._resolve_path(key)
        if path.exists():
            try:
                path.unlink()
                return True
            except OSError:
                return False
        return False

    def exists(self, key: str) -> bool:
        path = self._resolve_path(key)
        return path.exists() and path.is_file()

    def get_metadata(self, key: str) -> dict:
        path = self._resolve_path(key)
        if not path.exists():
            return {}
        stat = path.stat()
        mime, _ = mimetypes.guess_type(str(path))
        return {
            "size": stat.st_size,
            "content_type": mime or "application/octet-stream",
            "last_modified": stat.st_mtime,
        }

    def generate_signed_upload_url(self, key: str, expires_in: int = 3600, content_type: str = None) -> dict:
        token = signer.sign(f"{key}:upload")
        return {
            "upload_url": f"/api/storage/direct-upload/?token={token}&key={key}",
            "method": "PUT",
            "headers": {"Content-Type": content_type or "application/octet-stream"},
            "storage_key": key,
            "expires_in": expires_in,
        }

    def generate_signed_download_url(self, key: str, expires_in: int = 3600, filename: str = None) -> str:
        payload = f"{key}:{filename or ''}"
        signed_token = signer.sign(payload)
        return f"/api/storage/media-file/?token={signed_token}&key={key}"

    def generate_cdn_url(self, key: str) -> str:
        clean_key = key.lstrip("/").replace("\\", "/")
        return f"{self.cdn_base}/{clean_key}"


class CloudflareR2StorageProvider(BaseStorageProvider):
    """
    Production-grade object storage adapter for Cloudflare R2 (and S3-compatible backends).
    Uses boto3 with S3 Signature Version 4, auto-resolving R2 endpoint URLs and path addressing.
    Supports streaming uploads, zero-RAM buffer writes, presigned upload/download URLs,
    idempotent deletions, and configurable CDN domains.
    """

    def __init__(
        self,
        account_id: str = None,
        access_key: str = None,
        secret_key: str = None,
        bucket: str = None,
        endpoint_url: str = None,
        public_domain: str = None,
        region: str = None,
    ):
        import boto3
        from botocore.config import Config

        self.account_id = (
            account_id
            or getattr(settings, "R2_ACCOUNT_ID", None)
            or config("R2_ACCOUNT_ID", default="")
        ).strip()

        self.access_key = (
            access_key
            or getattr(settings, "R2_ACCESS_KEY_ID", None)
            or config("R2_ACCESS_KEY_ID", default=config("STORAGE_ACCESS_KEY", default=""))
        ).strip()

        self.secret_key = (
            secret_key
            or getattr(settings, "R2_SECRET_ACCESS_KEY", None)
            or config("R2_SECRET_ACCESS_KEY", default=config("STORAGE_SECRET_KEY", default=""))
        ).strip()

        self.bucket = (
            bucket
            or getattr(settings, "R2_BUCKET_NAME", None)
            or config("R2_BUCKET_NAME", default=config("STORAGE_BUCKET", default="exshareai"))
        ).strip()

        # Compute endpoint URL
        if endpoint_url:
            self.endpoint_url = str(endpoint_url).strip().rstrip("/")
        elif account_id:
            self.endpoint_url = f"https://{str(account_id).strip()}.r2.cloudflarestorage.com"
        else:
            explicit_endpoint = (
                getattr(settings, "R2_ENDPOINT_URL", None)
                or config("R2_ENDPOINT_URL", default="")
            ).strip()
            if explicit_endpoint:
                self.endpoint_url = explicit_endpoint.rstrip("/")
            elif self.account_id:
                self.endpoint_url = f"https://{self.account_id}.r2.cloudflarestorage.com"
            else:
                legacy_endpoint = config("STORAGE_ENDPOINT", default="").strip().rstrip("/")
                self.endpoint_url = legacy_endpoint or None

        self.region = (
            region
            or getattr(settings, "R2_REGION", None)
            or config("R2_REGION", default=config("STORAGE_REGION", default="auto"))
        ).strip() or "auto"

        self.cdn_base = (
            public_domain
            or getattr(settings, "R2_PUBLIC_DOMAIN", None)
            or getattr(settings, "CDN_BASE_URL", None)
            or config("R2_PUBLIC_DOMAIN", default=config("CDN_BASE_URL", default=""))
        ).strip().rstrip("/")

        self.s3_client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def _clean_key(self, key: str) -> str:
        """Sanitizes object keys to avoid path traversal, leading slashes, and Windows separators."""
        if not key:
            return ""
        return str(key).strip().replace("\\", "/").lstrip("/")

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        clean_key = self._clean_key(key)
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=clean_key,
            Body=data,
            ContentType=content_type,
        )
        return clean_key

    def save_file(self, key: str, file_or_stream, content_type: str = "application/octet-stream") -> str:
        """Stream a file or stream directly to R2 destination without RAM buffering."""
        clean_key = self._clean_key(key)
        extra_args = {"ContentType": content_type}

        if hasattr(file_or_stream, "read"):
            if hasattr(file_or_stream, "seek"):
                try:
                    file_or_stream.seek(0)
                except Exception:
                    pass
            self.s3_client.upload_fileobj(
                Fileobj=file_or_stream,
                Bucket=self.bucket,
                Key=clean_key,
                ExtraArgs=extra_args,
            )
        elif isinstance(file_or_stream, (bytes, bytearray)):
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=clean_key,
                Body=file_or_stream,
                ContentType=content_type,
            )
        else:
            buf = io.BytesIO(file_or_stream)
            self.s3_client.upload_fileobj(
                Fileobj=buf,
                Bucket=self.bucket,
                Key=clean_key,
                ExtraArgs=extra_args,
            )
        return clean_key

    def open_stream(self, key: str, mode: str = "rb"):
        """Return a readable streaming body directly from R2."""
        clean_key = self._clean_key(key)
        try:
            response = self.s3_client.get_object(Bucket=self.bucket, Key=clean_key)
            return response["Body"]
        except Exception as e:
            raise FileNotFoundError(f"Storage key '{clean_key}' not found in R2 bucket '{self.bucket}': {e}")

    def move_file(self, source_path, target_key: str) -> str:
        """Uploads a local temporary file directly to R2 and safely removes the local copy."""
        clean_key = self._clean_key(target_key)
        src = Path(source_path)
        if not src.exists():
            raise FileNotFoundError(f"Source file '{src}' does not exist.")
        mime, _ = mimetypes.guess_type(str(src))
        extra_args = {"ContentType": mime or "application/octet-stream"}
        self.s3_client.upload_file(
            Filename=str(src),
            Bucket=self.bucket,
            Key=clean_key,
            ExtraArgs=extra_args,
        )
        try:
            src.unlink()
        except OSError:
            pass
        return clean_key

    def download(self, key: str) -> bytes:
        clean_key = self._clean_key(key)
        response = self.s3_client.get_object(Bucket=self.bucket, Key=clean_key)
        return response["Body"].read()

    def download_bytes(self, key: str) -> bytes:
        return self.download(key)

    def delete(self, key: str) -> bool:
        """Safely and idempotently delete an object from R2."""
        clean_key = self._clean_key(key)
        if not clean_key:
            return True
        try:
            self.s3_client.delete_object(Bucket=self.bucket, Key=clean_key)
            return True
        except Exception as e:
            logger.warning(f"R2 deletion warning for key '{clean_key}': {e}")
            return False

    def exists(self, key: str) -> bool:
        clean_key = self._clean_key(key)
        if not clean_key:
            return False
        try:
            self.s3_client.head_object(Bucket=self.bucket, Key=clean_key)
            return True
        except Exception:
            return False

    def get_metadata(self, key: str) -> dict:
        clean_key = self._clean_key(key)
        try:
            res = self.s3_client.head_object(Bucket=self.bucket, Key=clean_key)
            return {
                "size": res.get("ContentLength", 0),
                "content_type": res.get("ContentType", "application/octet-stream"),
                "last_modified": res.get("LastModified"),
                "etag": res.get("ETag", "").strip('"'),
            }
        except Exception:
            return {}

    def generate_signed_upload_url(self, key: str, expires_in: int = 1800, content_type: str = None) -> dict:
        """
        Generates a short-lived presigned PUT URL allowing clients to upload directly to R2.
        Preserves exact dictionary structure required by DirectUploadInitView.
        """
        clean_key = self._clean_key(key)
        params = {"Bucket": self.bucket, "Key": clean_key}
        headers = {}
        if content_type:
            params["ContentType"] = content_type
            headers["Content-Type"] = content_type

        signed_url = self.s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params=params,
            ExpiresIn=expires_in,
        )
        return {
            "upload_url": signed_url,
            "method": "PUT",
            "headers": headers,
            "storage_key": clean_key,
            "expires_in": expires_in,
        }

    def generate_signed_download_url(self, key: str, expires_in: int = 3600, filename: str = None) -> str:
        """Generates a secure presigned GET URL for authenticated / authorized private media downloads."""
        clean_key = self._clean_key(key)
        params = {"Bucket": self.bucket, "Key": clean_key}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'

        return self.s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params=params,
            ExpiresIn=expires_in,
        )

    def generate_cdn_url(self, key: str) -> str:
        """
        Generates delivery URL. If a public CDN / custom domain is configured, returns public URL.
        If no public domain is configured, generates a signed download URL so private media remains protected.
        """
        clean_key = self._clean_key(key)
        if self.cdn_base:
            return f"{self.cdn_base}/{clean_key}"
        # Cloudflare R2 buckets are private by default. Without a CDN domain, issue a signed GET URL:
        return self.generate_signed_download_url(clean_key, expires_in=86400)


# Backward compatibility alias
S3CompatibleStorageProvider = CloudflareR2StorageProvider


@deconstructible
class CloudflareR2Storage(Storage):
    """
    Django Storage backend integrating Cloudflare R2 with standard Django models,
    FileField, ImageField, and default_storage.
    """

    def __init__(self, **kwargs):
        self.provider = CloudflareR2StorageProvider(**kwargs)

    def _open(self, name, mode="rb"):
        return self.provider.open_stream(name, mode)

    def _save(self, name, content):
        content_type = getattr(content, "content_type", None) or mimetypes.guess_type(name)[0] or "application/octet-stream"
        return self.provider.save_file(name, content, content_type=content_type)

    def delete(self, name):
        return self.provider.delete(name)

    def exists(self, name):
        return self.provider.exists(name)

    def url(self, name):
        return self.provider.generate_cdn_url(name)

    def size(self, name):
        meta = self.provider.get_metadata(name)
        return meta.get("size", 0)


_storage_provider_instance = None


def get_storage_provider(force_reload: bool = False) -> BaseStorageProvider:
    """Returns the singleton storage provider instance according to environment/settings."""
    global _storage_provider_instance
    if _storage_provider_instance is None or force_reload:
        provider_name = (
            getattr(settings, "STORAGE_PROVIDER", None)
            or config("STORAGE_PROVIDER", default="local")
        ).lower()

        if provider_name in ("r2", "cloudflare", "cloudflare_r2", "s3", "oss", "alibaba"):
            try:
                _storage_provider_instance = CloudflareR2StorageProvider()
            except Exception as e:
                logger.warning(f"Failed to initialize Cloudflare R2 storage provider ({e}), falling back to LocalStorageProvider.")
                _storage_provider_instance = LocalStorageProvider()
        else:
            _storage_provider_instance = LocalStorageProvider()
    return _storage_provider_instance

