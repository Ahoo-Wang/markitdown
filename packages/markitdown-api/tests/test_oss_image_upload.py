import base64
import hashlib
import inspect
import logging
from datetime import datetime, timezone

import pytest

from markitdown import DocumentConverterResult
from markitdown_api.api_converter import ApiConverter
from markitdown_api.api_types import ConvertRequest
from markitdown_api.convert_file import convert_file, convert_file_markdown
from markitdown_api.oss_image_upload import (
    OssImageUploader,
    _credentials_provider_from_environment,
    replace_data_images_with_oss_urls,
)


def test_replace_data_images_uploads_and_rewrites_markdown_image():
    image_bytes = b"fake-png-bytes"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    markdown = f'before ![chart](data:image/png;base64,{encoded} "Chart") after'

    class FakeUploader:
        def __init__(self):
            self.calls = []

        def upload_image(self, mimetype, content):
            self.calls.append((mimetype, content))
            return "https://cdn.example.com/images/chart.png"

    uploader = FakeUploader()

    rewritten = replace_data_images_with_oss_urls(
        markdown, uploader_factory=lambda: uploader
    )

    assert rewritten == (
        'before ![chart](https://cdn.example.com/images/chart.png "Chart") after'
    )
    assert uploader.calls == [("image/png", image_bytes)]


def test_replace_data_images_keeps_data_uri_when_oss_is_unavailable():
    image_bytes = b"fake-png-bytes"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    markdown = f"![chart](data:image/png;base64,{encoded})"

    def unavailable_uploader():
        raise ValueError("OSS_ENDPOINT is not set")

    assert (
        replace_data_images_with_oss_urls(
            markdown, uploader_factory=unavailable_uploader
        )
        == markdown
    )


def test_replace_data_images_logs_expected_oss_unavailable_fallback_as_info(caplog):
    image_bytes = b"fake-png-bytes"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    markdown = f"![chart](data:image/png;base64,{encoded})"

    def unavailable_uploader():
        raise ValueError("OSS_ENDPOINT is not set")

    caplog.set_level(logging.INFO, logger="markitdown_api.oss_image_upload")

    assert (
        replace_data_images_with_oss_urls(
            markdown, uploader_factory=unavailable_uploader
        )
        == markdown
    )
    assert any(
        record.levelno == logging.INFO
        and "OSS image uploader is unavailable" in record.message
        for record in caplog.records
    )
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


def test_replace_data_images_keeps_data_uri_when_single_upload_fails():
    image_bytes = b"fake-png-bytes"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    markdown = f"![chart](data:image/png;base64,{encoded})"

    class FailingUploader:
        def upload_image(self, mimetype, content):
            raise RuntimeError("network timeout")

    assert (
        replace_data_images_with_oss_urls(markdown, uploader_factory=FailingUploader)
        == markdown
    )


def test_oss_image_uploader_uses_stable_hash_key_and_public_url():
    image_bytes = b"fake-png-bytes"
    digest = hashlib.sha256(image_bytes).hexdigest()
    fixed_now = datetime(2026, 6, 1, tzinfo=timezone.utc)

    class FakeBucket:
        def __init__(self):
            self.calls = []

        def put_object(self, key, content, headers=None):
            self.calls.append((key, content, headers))

    bucket = FakeBucket()
    uploader = OssImageUploader(
        bucket=bucket,
        endpoint="https://oss-cn-hangzhou.aliyuncs.com",
        bucket_name="markitdown",
        key_prefix="converted-images",
        now=lambda: fixed_now,
    )

    url = uploader.upload_image("image/png", image_bytes)

    expected_key = f"converted-images/2026/06/01/{digest}.png"
    assert bucket.calls == [
        (
            expected_key,
            image_bytes,
            {
                "Content-Disposition": "inline",
                "Content-Type": "image/png",
                "x-oss-object-acl": "public-read",
            },
        )
    ]
    assert url == f"https://markitdown.oss-cn-hangzhou.aliyuncs.com/{expected_key}"


def test_oss_image_uploader_rejects_unknown_image_mimetype():
    uploader = OssImageUploader(
        bucket=object(),
        endpoint="https://oss-cn-hangzhou.aliyuncs.com",
        bucket_name="markitdown",
    )

    with pytest.raises(ValueError, match="Unsupported image mimetype"):
        uploader.upload_image("application/octet-stream", b"payload")


def test_oss_credentials_provider_accepts_secret_access_key_alias(monkeypatch):
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "access-key-id")
    monkeypatch.delenv("OSS_ACCESS_KEY_SECRET", raising=False)
    monkeypatch.setenv("OSS_SECRET_ACCESS_KEY", "secret-access-key")

    import oss2

    provider = _credentials_provider_from_environment(oss2.credentials)
    credentials = provider.get_credentials()

    assert credentials.get_access_key_id() == "access-key-id"
    assert credentials.get_access_key_secret() == "secret-access-key"


def test_oss_credentials_provider_missing_secret_mentions_both_supported_names(
    monkeypatch,
):
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "access-key-id")
    monkeypatch.delenv("OSS_ACCESS_KEY_SECRET", raising=False)
    monkeypatch.delenv("OSS_SECRET_ACCESS_KEY", raising=False)

    with pytest.raises(
        ValueError, match="OSS_ACCESS_KEY_SECRET.*OSS_SECRET_ACCESS_KEY"
    ):
        _credentials_provider_from_environment(object())


def test_convert_request_disables_keep_data_uris_by_default():
    assert ConvertRequest().keep_data_uris is False


def test_file_upload_endpoints_disable_keep_data_uris_by_default():
    assert inspect.signature(convert_file).parameters["keep_data_uris"].default is False
    assert (
        inspect.signature(convert_file_markdown).parameters["keep_data_uris"].default
        is False
    )


def test_api_converter_rewrites_embedded_images_after_conversion(monkeypatch):
    image_bytes = b"fake-png-bytes"
    encoded = base64.b64encode(image_bytes).decode("ascii")
    markdown = f"![chart](data:image/png;base64,{encoded})"
    seen_kwargs = {}

    class StubApiConverter(ApiConverter):
        def _internal_convert(self, **kwargs):
            seen_kwargs.update(kwargs)
            return DocumentConverterResult(markdown=markdown)

    def fake_replace(markdown_value):
        assert markdown_value == markdown
        return "![chart](https://cdn.example.com/images/chart.png)"

    monkeypatch.setattr(
        "markitdown_api.api_converter.replace_data_images_with_oss_urls",
        fake_replace,
    )

    response = StubApiConverter(ConvertRequest()).convert()

    assert seen_kwargs["keep_data_uris"] is False
    assert (
        response.result.markdown == "![chart](https://cdn.example.com/images/chart.png)"
    )
