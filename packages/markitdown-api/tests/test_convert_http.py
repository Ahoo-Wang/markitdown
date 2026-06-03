from markitdown import DocumentConverterResult

from markitdown_api.commons import HTTP_VERIFY_SSL_ENV
from markitdown_api.convert_http import HttpApiConverter
from markitdown_api.convert_http_request import ConvertHttpRequest


def _convert_and_capture_http_request(monkeypatch):
    request_calls = []
    url = "https://example.invalid/"

    class FakeResponse:
        content = b"<html>ok</html>"
        headers = {"Content-Type": "text/html; charset=utf-8"}

    response = FakeResponse()

    class FakeMarkItDown:
        def convert_response(self, response, stream_info, **kwargs):
            return DocumentConverterResult(markdown="ok")

    def fake_request(**kwargs):
        request_calls.append(kwargs)
        return response

    monkeypatch.setattr(
        "markitdown_api.api_converter.build_markitdown",
        lambda request: FakeMarkItDown(),
    )
    monkeypatch.setattr("markitdown_api.convert_http.requests.request", fake_request)

    result = HttpApiConverter(
        ConvertHttpRequest(
            url=url,
            headers={"Accept": "text/html"},
        )
    )._internal_convert()

    assert result.markdown == "ok"
    assert len(request_calls) == 1
    return request_calls[0]


def test_http_converter_enables_ssl_verification_by_default(monkeypatch):
    monkeypatch.delenv(HTTP_VERIFY_SSL_ENV, raising=False)

    request_call = _convert_and_capture_http_request(monkeypatch)

    assert request_call == {
        "method": "get",
        "url": "https://example.invalid/",
        "headers": {
            "Accept": "text/html",
            "Referer": "https://example.invalid/",
        },
        "verify": True,
    }


def test_http_converter_enables_ssl_verification_when_configured_true(monkeypatch):
    monkeypatch.setenv(HTTP_VERIFY_SSL_ENV, "true")

    request_call = _convert_and_capture_http_request(monkeypatch)

    assert request_call == {
        "method": "get",
        "url": "https://example.invalid/",
        "headers": {
            "Accept": "text/html",
            "Referer": "https://example.invalid/",
        },
        "verify": True,
    }


def test_http_converter_disables_ssl_verification_when_configured_false(monkeypatch):
    monkeypatch.setenv(HTTP_VERIFY_SSL_ENV, "false")

    request_call = _convert_and_capture_http_request(monkeypatch)

    assert request_call == {
        "method": "get",
        "url": "https://example.invalid/",
        "headers": {
            "Accept": "text/html",
            "Referer": "https://example.invalid/",
        },
        "verify": False,
    }


def test_http_converter_adds_same_origin_referer_by_default(monkeypatch):
    request_calls = []
    url = "https://downloads.example.test/_Resources/images/document.pdf"

    class FakeResponse:
        content = b"%PDF-1.4\n"
        headers = {"Content-Type": "application/pdf"}

    class FakeMarkItDown:
        def convert_response(self, response, stream_info, **kwargs):
            return DocumentConverterResult(markdown="ok")

    def fake_request(**kwargs):
        request_calls.append(kwargs)
        return FakeResponse()

    monkeypatch.setattr(
        "markitdown_api.api_converter.build_markitdown",
        lambda request: FakeMarkItDown(),
    )
    monkeypatch.setattr("markitdown_api.convert_http.requests.request", fake_request)

    result = HttpApiConverter(
        ConvertHttpRequest(
            url=url,
            headers={
                "user-agent": "Mozilla/5.0",
            },
        )
    )._internal_convert()

    assert result.markdown == "ok"
    assert request_calls == [
        {
            "method": "get",
            "url": url,
            "headers": {
                "user-agent": "Mozilla/5.0",
                "Referer": "https://downloads.example.test/",
            },
            "verify": True,
        },
    ]


def test_http_converter_preserves_explicit_referer(monkeypatch):
    request_calls = []
    url = "https://downloads.example.test/_Resources/images/document.pdf"

    class FakeResponse:
        content = b"%PDF-1.4\n"
        headers = {"Content-Type": "application/pdf"}

    class FakeMarkItDown:
        def convert_response(self, response, stream_info, **kwargs):
            return DocumentConverterResult(markdown="ok")

    def fake_request(**kwargs):
        request_calls.append(kwargs)
        return FakeResponse()

    monkeypatch.setattr(
        "markitdown_api.api_converter.build_markitdown",
        lambda request: FakeMarkItDown(),
    )
    monkeypatch.setattr("markitdown_api.convert_http.requests.request", fake_request)

    result = HttpApiConverter(
        ConvertHttpRequest(
            url=url,
            headers={
                "referer": "https://example.com/custom",
            },
        )
    )._internal_convert()

    assert result.markdown == "ok"
    assert request_calls == [
        {
            "method": "get",
            "url": url,
            "headers": {
                "referer": "https://example.com/custom",
            },
            "verify": True,
        },
    ]
