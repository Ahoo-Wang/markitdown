import sys
from typing import Any

from markitdown import DocumentConverterResult
from markitdown_api.api_types import (
    ConvertRequest,
    ConvertResult,
    ConvertResponse,
    StreamMetadata,
    FailedAttempt,
    FailedResult,
)
from markitdown_api.commons import build_markitdown
from markitdown_api.storages.storager_registrar import StoragerRegistrar


def remove_all_zw_chars(text: str) -> str:
    zw_chars = ["\u200B", "\u200C", "\u200D", "\uFEFF"]
    for char in zw_chars:
        text = text.replace(char, "")
    return text


class ApiConverter:
    def __init__(self, request: ConvertRequest):
        self.metadata: StreamMetadata | None = None
        self.request = request
        self.markitdown = build_markitdown(request)

    def convert(self) -> ConvertResponse:
        converted_result: DocumentConverterResult = self._internal_convert(
            llm_prompt=self.request.get_llm_prompt(),
            keep_data_uris=self.request.keep_data_uris,
            selector=self.request.html.selector if self.request.html else None,
        )
        markdown = remove_all_zw_chars(converted_result.markdown)
        result = ConvertResult(
            title=converted_result.title,
            markdown=markdown,
        )
        if converted_result.mimetype:
            result.mimetype = converted_result.mimetype
        storage_result = None
        if self.request.storage:
            storage_result = StoragerRegistrar().storage(
                self.request.storage, self.metadata, result
            )
            result.markdown = ""
        failed_attempts = None
        if converted_result.failed_attempts:
            failed_attempts = []
            for attempt in converted_result.failed_attempts:
                converter = type(attempt.converter).__name__
                error_type = ""
                error_msg = ""
                if attempt.exc_info:
                    error_type = attempt.exc_info[0].__name__
                    error_msg = str(attempt.exc_info[1])
                failed_attempts.append(
                    FailedAttempt(
                        converter=converter, error_type=error_type, error_msg=error_msg
                    )
                )

        failed_result = None
        if failed_attempts:
            failed_result = FailedResult(attempts=failed_attempts)
        return ConvertResponse(
            metadata=self.metadata,
            result=result,
            storage=storage_result,
            failed=failed_result,
        )

    def _internal_convert(self, **kwargs: Any) -> DocumentConverterResult:
        raise NotImplementedError
