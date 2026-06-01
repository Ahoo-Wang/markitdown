import base64
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import Callable, Protocol
from urllib.parse import quote, urlparse, urlunparse

logger = logging.getLogger(__name__)

_DATA_IMAGE_RE = re.compile(
    r"!\[(?P<alt>(?:\\.|[^\]])*)\]"
    r"\("
    r"(?P<uri>data:(?P<mimetype>image/[A-Za-z0-9.+-]+);base64,(?P<payload>[A-Za-z0-9+/=\r\n]+))"
    r"(?P<title>\s+\"(?:\\.|[^\"])*\")?"
    r"\)"
)

_IMAGE_EXTENSIONS = {
    "image/bmp": "bmp",
    "image/gif": "gif",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/svg+xml": "svg",
    "image/webp": "webp",
}


def _credentials_provider_from_environment(credentials_module):
    access_key_id = os.environ.get("OSS_ACCESS_KEY_ID")
    access_key_secret = os.environ.get("OSS_ACCESS_KEY_SECRET") or os.environ.get(
        "OSS_SECRET_ACCESS_KEY"
    )
    security_token = os.environ.get("OSS_SESSION_TOKEN")

    if not access_key_id:
        raise ValueError("OSS_ACCESS_KEY_ID is not set")
    if not access_key_secret:
        raise ValueError("OSS_ACCESS_KEY_SECRET is not set")

    return credentials_module.StaticCredentialsProvider(
        access_key_id,
        access_key_secret,
        security_token,
    )


class ImageUploader(Protocol):
    def upload_image(self, mimetype: str, content: bytes) -> str:
        """Upload an image and return its public URL."""


class OssImageUploader:
    def __init__(
        self,
        *,
        bucket=None,
        endpoint: str | None = None,
        bucket_name: str | None = None,
        key_prefix: str | None = None,
        public_base_url: str | None = None,
        object_acl: str | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.endpoint = endpoint or os.environ.get("OSS_ENDPOINT")
        if self.endpoint is None:
            raise ValueError("OSS_ENDPOINT is not set")

        self.bucket_name = bucket_name or os.environ.get("OSS_BUCKET")
        if self.bucket_name is None:
            raise ValueError("OSS_BUCKET is not set")

        self.key_prefix = (
            key_prefix or os.environ.get("OSS_IMAGE_KEY_PREFIX") or "images"
        ).strip("/")
        self._public_base_url = (
            public_base_url or os.environ.get("OSS_PUBLIC_BASE_URL") or ""
        ).rstrip("/")
        self.object_acl = (
            object_acl or os.environ.get("OSS_OBJECT_ACL") or "public-read"
        )
        self._now = now or (lambda: datetime.now(timezone.utc))

        if bucket is None:
            import oss2

            oss_region_key = "OSS_REGION"
            region = os.environ.get(oss_region_key)
            if region is None:
                raise ValueError(f"{oss_region_key} is not set")

            credentials_provider = _credentials_provider_from_environment(
                oss2.credentials
            )
            auth = oss2.ProviderAuthV4(credentials_provider)
            bucket = oss2.Bucket(
                auth,
                self.endpoint,
                self.bucket_name,
                region=region,
            )

        self.bucket = bucket

    def upload_image(self, mimetype: str, content: bytes) -> str:
        extension = self._extension_for_mimetype(mimetype)
        now = self._now().astimezone(timezone.utc)
        digest = hashlib.sha256(content).hexdigest()
        key_parts = [
            self.key_prefix,
            f"{now:%Y}",
            f"{now:%m}",
            f"{now:%d}",
            f"{digest}.{extension}",
        ]
        key = "/".join(part for part in key_parts if part)
        self.bucket.put_object(
            key,
            content,
            headers={
                "Content-Type": mimetype,
                "x-oss-object-acl": self.object_acl,
            },
        )
        return self._object_url(key)

    def _extension_for_mimetype(self, mimetype: str) -> str:
        extension = _IMAGE_EXTENSIONS.get(mimetype.lower())
        if extension is None:
            raise ValueError(f"Unsupported image mimetype: {mimetype}")
        return extension

    def _object_url(self, key: str) -> str:
        if self._public_base_url:
            return f"{self._public_base_url}/{quote(key, safe='/')}"

        endpoint = self.endpoint.rstrip("/")
        if "://" not in endpoint:
            endpoint = f"https://{endpoint}"

        parsed = urlparse(endpoint)
        host = parsed.netloc
        if not host.startswith(f"{self.bucket_name}."):
            host = f"{self.bucket_name}.{host}"

        path = parsed.path.rstrip("/")
        object_path = (
            f"{path}/{quote(key, safe='/')}" if path else f"/{quote(key, safe='/')}"
        )
        return urlunparse((parsed.scheme, host, object_path, "", "", ""))


def replace_data_images_with_oss_urls(
    markdown: str,
    *,
    uploader_factory: Callable[[], ImageUploader] = OssImageUploader,
) -> str:
    if "data:image/" not in markdown:
        return markdown

    try:
        uploader = uploader_factory()
    except Exception as exc:
        logger.warning(
            "OSS image uploader is unavailable; keeping data URI images: %s", exc
        )
        return markdown

    def replace(match: re.Match) -> str:
        mimetype = match.group("mimetype")
        payload = "".join(match.group("payload").split())
        try:
            content = base64.b64decode(payload, validate=True)
            url = uploader.upload_image(mimetype, content)
        except Exception as exc:
            logger.warning(
                "Failed to upload embedded image to OSS; keeping data URI: %s",
                exc,
            )
            return match.group(0)

        title = match.group("title") or ""
        return f"![{match.group('alt')}]({url}{title})"

    return _DATA_IMAGE_RE.sub(replace, markdown)
