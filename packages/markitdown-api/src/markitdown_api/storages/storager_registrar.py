from typing import Any

from markitdown_api.api_types import (
    StorageOptions,
    StreamMetadata,
    ConvertResult,
    StorageResult,
)
from markitdown_api.storages.oss_storager import OssStorager
from markitdown_api.storages.storager import Storager


class StoragerRegistrar(Storager):
    type = "__registrar__"

    def storage(
        self,
        options: StorageOptions,
        metadata: StreamMetadata,
        result: ConvertResult,
        **kwargs: Any,
    ) -> StorageResult:
        if options.type != "oss":
            raise ValueError(f"Unsupported storage type: {options.type}")
        return OssStorager().storage(options, metadata, result)
