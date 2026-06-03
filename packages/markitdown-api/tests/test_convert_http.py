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
        "headers": {"Accept": "text/html"},
        "verify": True,
    }


def test_http_converter_enables_ssl_verification_when_configured_true(monkeypatch):
    monkeypatch.setenv(HTTP_VERIFY_SSL_ENV, "true")

    request_call = _convert_and_capture_http_request(monkeypatch)

    assert request_call == {
        "method": "get",
        "url": "https://example.invalid/",
        "headers": {"Accept": "text/html"},
        "verify": True,
    }


def test_http_converter_disables_ssl_verification_when_configured_false(monkeypatch):
    monkeypatch.setenv(HTTP_VERIFY_SSL_ENV, "false")

    request_call = _convert_and_capture_http_request(monkeypatch)

    assert request_call == {
        "method": "get",
        "url": "https://example.invalid/",
        "headers": {"Accept": "text/html"},
        "verify": False,
    }
