from typing import Any

from markitdown_api.api_types import (
    ConvertRequest,
    ConvertResult,
    ConvertResponse,
    StreamMetadata,
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
        self.markitdown = build_markitdown(request.llm)

    def convert(self) -> ConvertResponse:
        converted_result = self._internal_convert(
            llm_prompt=self.request.get_llm_prompt(),
            keep_data_uris=self.request.keep_data_uris,
        )

        result = ConvertResult(
            title=converted_result.title,
            markdown=remove_all_zw_chars(converted_result.markdown),
        )
        storage_result = None
        if self.request.storage:
            storage_result = StoragerRegistrar().storage(
                self.request.storage, self.metadata, converted_result
            )
            result = None

        return ConvertResponse(
            metadata=self.metadata,
            result=result,
            storage=storage_result,
        )

    def _internal_convert(self, **kwargs: Any) -> ConvertResult:
        raise NotImplementedError
