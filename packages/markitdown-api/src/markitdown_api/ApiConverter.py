from typing import Any

from markitdown_api.api_types import (
    ConvertRequest,
    ConvertResult,
    ConvertResponse,
    StreamMetadata,
)
from markitdown_api.commons import build_markitdown


class ApiConverter:
    def __init__(self, request: ConvertRequest):
        self.metadata: StreamMetadata | None = None
        self.request = request
        self.markitdown = build_markitdown(request.llm)

    def convert(self) -> ConvertResponse:
        result = self._internal_convert(
            llm_prompt=self.request.get_llm_prompt(),
            keep_data_uris=self.request.keep_data_uris,
        )
        return ConvertResponse(
            metadata=self.metadata,
            result=result,
        )

    def _internal_convert(self, **kwargs: Any) -> ConvertResult:
        raise NotImplementedError
