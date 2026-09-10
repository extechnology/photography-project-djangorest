import os
import io
import mimetypes
from pathlib import Path
from django.conf import settings
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from decouple import config

signer = TimestampSigner()


class BaseStorageProvider:
    """Abstract interface for cloud/local object storage providers."""

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        raise NotImplementedError

    def download(self, key: str) -> bytes:
        raise NotImplementedError

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
        clean_key = key.lstrip("/").replace("\\", "/")
        full_path = self.base_dir / clean_key
        full_path.parent.mkdir(parents=True, exist_ok=True)
        return full_path

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._resolve_path(key)
        with open(path, "wb") as f:
            f.write(data)
        return key

    def download(self, key: str) -> bytes:
        path = self._resolve_path(key)
        if not path.exists():
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
        return self._resolve_path(key).exists()

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


class S3CompatibleStorageProvider(BaseStorageProvider):
    """
    Production-grade object storage adapter for AWS S3, Cloudflare R2, and Alibaba Cloud OSS.
    Uses boto3 with S3 Signature Version 4.
    """

    def __init__(self):
        import boto3
        from botocore.config import Config

        self.endpoint_url = config("STORAGE_ENDPOINT", default=None)
        self.access_key = config("STORAGE_ACCESS_KEY", default="")
        self.secret_key = config("STORAGE_SECRET_KEY", default="")
        self.bucket = config("STORAGE_BUCKET", default="photography-media")
        self.region = config("STORAGE_REGION", default="us-east-1")
        self.cdn_base = config("CDN_BASE_URL", default="").rstrip("/")

        self.s3_client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual" if not self.endpoint_url else "path"}),
        )

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key

    def download(self, key: str) -> bytes:
        response = self.s3_client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def delete(self, key: str) -> bool:
        try:
            self.s3_client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def exists(self, key: str) -> bool:
        try:
            self.s3_client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def get_metadata(self, key: str) -> dict:
        try:
            res = self.s3_client.head_object(Bucket=self.bucket, Key=key)
            return {
                "size": res.get("ContentLength", 0),
                "content_type": res.get("ContentType", "application/octet-stream"),
                "last_modified": res.get("LastModified"),
            }
        except Exception:
            return {}

    def generate_signed_upload_url(self, key: str, expires_in: int = 3600, content_type: str = None) -> dict:
        params = {"Bucket": self.bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type

        signed_url = self.s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params=params,
            ExpiresIn=expires_in,
        )
        return {
            "upload_url": signed_url,
            "method": "PUT",
            "headers": {"Content-Type": content_type} if content_type else {},
            "storage_key": key,
            "expires_in": expires_in,
        }

    def generate_signed_download_url(self, key: str, expires_in: int = 3600, filename: str = None) -> str:
        params = {"Bucket": self.bucket, "Key": key}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'

        return self.s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params=params,
            ExpiresIn=expires_in,
        )

    def generate_cdn_url(self, key: str) -> str:
        clean_key = key.lstrip("/")
        if self.cdn_base:
            return f"{self.cdn_base}/{clean_key}"
        if self.endpoint_url:
            return f"{self.endpoint_url.rstrip('/')}/{self.bucket}/{clean_key}"
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{clean_key}"


_storage_provider_instance = None


def get_storage_provider() -> BaseStorageProvider:
    """Returns the singleton storage provider instance according to environment/settings."""
    global _storage_provider_instance
    if _storage_provider_instance is None:
        provider_name = config("STORAGE_PROVIDER", default="local").lower()
        if provider_name in ("s3", "r2", "oss", "alibaba"):
            try:
                _storage_provider_instance = S3CompatibleStorageProvider()
            except Exception:
                # Fallback to local if credentials missing or misconfigured
                _storage_provider_instance = LocalStorageProvider()
        else:
            _storage_provider_instance = LocalStorageProvider()
    return _storage_provider_instance
