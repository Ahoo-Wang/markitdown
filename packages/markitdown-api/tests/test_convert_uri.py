from markitdown import DocumentConverterResult

from markitdown_api.commons import HTTP_VERIFY_SSL_ENV
from markitdown_api.convert_uri import ConvertUriRequest, UriApiConverter


def _convert_and_capture_session_verify(monkeypatch):
    captured = {}

    class FakeRequestSession:
        verify = True

    class FakeMarkItDown:
        def __init__(self):
            self._requests_session = FakeRequestSession()

        def convert_uri(self, uri, stream_info, **kwargs):
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
    return captured["markitdown"]._requests_session.verify


def test_uri_converter_disables_ssl_verification_by_default(monkeypatch):
    monkeypatch.delenv(HTTP_VERIFY_SSL_ENV, raising=False)

    verify = _convert_and_capture_session_verify(monkeypatch)

    assert verify is False


def test_uri_converter_enables_ssl_verification_when_configured(monkeypatch):
    monkeypatch.setenv(HTTP_VERIFY_SSL_ENV, "true")

    verify = _convert_and_capture_session_verify(monkeypatch)

    assert verify is True
