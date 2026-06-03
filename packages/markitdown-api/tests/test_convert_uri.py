from markitdown import DocumentConverterResult

from markitdown_api.commons import HTTP_VERIFY_SSL_ENV
from markitdown_api.convert_uri import ConvertUriRequest, UriApiConverter


def _convert_and_capture_session_get_request(monkeypatch):
    captured = {}

    class FakeResponse:
        headers = {"Content-Type": "application/pdf"}

        def raise_for_status(self):
            captured["raised_for_status"] = True

    class FakeRequestSession:
        def get(self, *args, **kwargs):
            captured["get"] = {"args": args, "kwargs": kwargs}
            return FakeResponse()

    class FakeMarkItDown:
        def __init__(self):
            self._requests_session = FakeRequestSession()

        def convert_uri(self, uri, stream_info, **kwargs):
            raise AssertionError("HTTP URI requests must pass verify explicitly")

        def convert_response(self, response, stream_info, **kwargs):
            captured["response"] = response
            return DocumentConverterResult(markdown="ok")

    def fake_build_markitdown(request):
        markitdown = FakeMarkItDown()
        captured["markitdown"] = markitdown
        return markitdown

    monkeypatch.setattr(
        "markitdown_api.api_converter.build_markitdown",
        fake_build_markitdown,
    )

    result = UriApiConverter(
        ConvertUriRequest(uri="https://example.invalid/document.pdf")
    )._internal_convert()

    assert result.markdown == "ok"
    assert captured["raised_for_status"] is True
    return captured["get"]


def test_uri_converter_enables_ssl_verification_by_default(monkeypatch):
    monkeypatch.delenv(HTTP_VERIFY_SSL_ENV, raising=False)

    request_call = _convert_and_capture_session_get_request(monkeypatch)

    assert request_call == {
        "args": ("https://example.invalid/document.pdf",),
        "kwargs": {"stream": True, "verify": True},
    }


def test_uri_converter_enables_ssl_verification_when_configured_true(monkeypatch):
    monkeypatch.setenv(HTTP_VERIFY_SSL_ENV, "true")

    request_call = _convert_and_capture_session_get_request(monkeypatch)

    assert request_call == {
        "args": ("https://example.invalid/document.pdf",),
        "kwargs": {"stream": True, "verify": True},
    }


def test_uri_converter_disables_ssl_verification_when_configured_false(monkeypatch):
    monkeypatch.setenv(HTTP_VERIFY_SSL_ENV, "false")

    request_call = _convert_and_capture_session_get_request(monkeypatch)

    assert request_call == {
        "args": ("https://example.invalid/document.pdf",),
        "kwargs": {"stream": True, "verify": False},
    }
