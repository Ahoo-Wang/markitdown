import json
from urllib.parse import quote

from markitdown import DocumentConverterResult

from markitdown_api.commons import HTTP_VERIFY_SSL_ENV
from markitdown_api.convert_http_request import ConvertHttpRequest
from markitdown_api.convert_yuque_api import (
    YuQueApiConverter,
    extract_yuque_app_data_url,
)


def _convert_and_capture_yuque_request(monkeypatch):
    request_calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "data": {
                    "title": "Doc",
                    "updated_at": "2025-05-19T07:20:41.000Z",
                    "content": "<p>ok</p>",
                }
            }

    class FakeMarkItDown:
        def convert_stream(self, stream, stream_info, **kwargs):
            return DocumentConverterResult(markdown="ok")

    def fake_get(**kwargs):
        request_calls.append(kwargs)
        return FakeResponse()

    monkeypatch.setattr(
        "markitdown_api.api_converter.build_markitdown",
        lambda request: FakeMarkItDown(),
    )
    monkeypatch.setattr("markitdown_api.convert_yuque_api.requests.get", fake_get)

    result = YuQueApiConverter(
        ConvertHttpRequest(
            url="https://example.invalid/api/docs/doc",
            headers={"Authorization": "Bearer token"},
        )
    )._internal_convert()

    assert result.markdown == "ok"
    assert len(request_calls) == 1
    return request_calls[0]


def test_yuque_converter_enables_ssl_verification_by_default(monkeypatch):
    monkeypatch.delenv(HTTP_VERIFY_SSL_ENV, raising=False)

    request_call = _convert_and_capture_yuque_request(monkeypatch)

    assert request_call == {
        "url": "https://example.invalid/api/docs/doc",
        "headers": {"Authorization": "Bearer token"},
        "verify": True,
    }


def test_yuque_converter_disables_ssl_verification_when_configured_false(
    monkeypatch,
):
    monkeypatch.setenv(HTTP_VERIFY_SSL_ENV, "false")

    request_call = _convert_and_capture_yuque_request(monkeypatch)

    assert request_call == {
        "url": "https://example.invalid/api/docs/doc",
        "headers": {"Authorization": "Bearer token"},
        "verify": False,
    }


def _extract_and_capture_yuque_book_request(monkeypatch):
    request_calls = []
    app_data = {
        "organization": {"login": "example"},
        "book": {"id": 1, "name": "Book", "toc": []},
    }
    encoded_app_data = quote(json.dumps(app_data))

    class FakeResponse:
        status_code = 200
        content = (
            f'window.appData = JSON.parse(decodeURIComponent("{encoded_app_data}"))'
        ).encode("utf-8")

    def fake_get(**kwargs):
        request_calls.append(kwargs)
        return FakeResponse()

    monkeypatch.setattr("markitdown_api.convert_yuque_api.requests.get", fake_get)

    assert extract_yuque_app_data_url("https://example.invalid/book") == app_data
    assert len(request_calls) == 1
    return request_calls[0]


def test_yuque_book_fetch_enables_ssl_verification_by_default(monkeypatch):
    monkeypatch.delenv(HTTP_VERIFY_SSL_ENV, raising=False)

    request_call = _extract_and_capture_yuque_book_request(monkeypatch)

    assert request_call == {
        "url": "https://example.invalid/book",
        "verify": True,
    }


def test_yuque_book_fetch_disables_ssl_verification_when_configured_false(
    monkeypatch,
):
    monkeypatch.setenv(HTTP_VERIFY_SSL_ENV, "false")

    request_call = _extract_and_capture_yuque_book_request(monkeypatch)

    assert request_call == {
        "url": "https://example.invalid/book",
        "verify": False,
    }
