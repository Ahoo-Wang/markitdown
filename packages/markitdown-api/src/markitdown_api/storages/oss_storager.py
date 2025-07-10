import os
from typing import Any

import oss2
from oss2.credentials import EnvironmentVariableCredentialsProvider

from markitdown_api.api_types import (
    StreamMetadata,
    ConvertResult,
    StorageOptions,
    StorageResult,
)
from markitdown_api.storages.storager import Storager

_utf8_charset = "utf-8"
_put_object_headers = {"Content-Type": f"text/markdown; charset={_utf8_charset}"}


class OssStorager(Storager):
    type = "oss"

    def __init__(self):
        environmentVariableCredentialsProvider = (
            EnvironmentVariableCredentialsProvider()
        )
        environmentVariableCredentialsProvider.get_credentials()
        self.auth = oss2.ProviderAuthV4(environmentVariableCredentialsProvider)
        oss_endpoint_key = "OSS_ENDPOINT"
        self.endpoint = os.environ.get(oss_endpoint_key)
        if self.endpoint is None:
            raise ValueError(f"{oss_endpoint_key} is not set")
        oss_region_key = "OSS_REGION"
        self.region = os.environ.get(oss_region_key)
        if self.region is None:
            raise ValueError(f"{oss_region_key} is not set")
        oss_bucket_key = "OSS_BUCKET"
        self.bucket_name = os.environ.get(oss_bucket_key)
        if self.bucket_name is None:
            raise ValueError(f"{oss_bucket_key} is not set")
        self.bucket = oss2.Bucket(
            self.auth,
            self.endpoint,
            self.bucket_name,
            region=self.region,
        )

    def storage(
        self,
        options: StorageOptions,
        metadata: StreamMetadata,
        result: ConvertResult,
        **kwargs: Any,
    ) -> StorageResult:
        headers = _put_object_headers
        if result.title:
            headers = _put_object_headers.copy()
            headers["x-oss-meta-title"] = result.title
        self.bucket.put_object(
            options.key, result.markdown.encode(_utf8_charset), headers=headers
        )
        return StorageResult(
            endpoint=self.endpoint,
            region=self.region,
            bucket=self.bucket_name,
            key=options.key,
        )
