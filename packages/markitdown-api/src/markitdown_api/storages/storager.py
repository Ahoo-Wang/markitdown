from typing import Any

from markitdown_api.api_types import (
    ConvertResult,
    StreamMetadata,
    StorageOptions,
    StorageResult,
)


class Storager:
    type: str

    def storage(
        self,
        options: StorageOptions,
        metadata: StreamMetadata,
        result: ConvertResult,
        **kwargs: Any,
    ) -> StorageResult:
        raise NotImplementedError
