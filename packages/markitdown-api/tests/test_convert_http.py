from markitdown import DocumentConverterResult

from markitdown_api.convert_http import HttpApiConverter
from markitdown_api.convert_http_request import ConvertHttpRequest


def test_http_converter_disables_ssl_verification_explicitly(monkeypatch):
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
    assert request_calls == [
        {
            "method": "get",
            "url": url,
            "headers": {"Accept": "text/html"},
            "verify": False,
        },
    ]
