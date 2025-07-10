from pydantic import BaseModel, Field
from starlette.responses import Response
from markitdown._llm_utils import get_llm_prompt


class LlmOptions(BaseModel):
    open_ai_base_url: str | None = Field(
        default=None, description="OpenAI API base URL"
    )
    open_ai_api_key: str | None = Field(default=None, description="OpenAI API key")
    model: str | None = Field(default=None, description="LLM model")
    prompt: str = get_llm_prompt()


class StorageOptions(BaseModel):
    type: str = Field(default="oss", description="Storage type")
    key: str | None = Field(default=None, description="Storage key")


class ConvertRequest(BaseModel):
    llm: LlmOptions | None = Field(default=None, description="LLM options")
    storage: StorageOptions | None = Field(default=None, description="Storage options")
    keep_data_uris: bool = Field(
        default=False,
        description="If keep_data_uris is True, use base64 encoding for images",
    )

    def get_llm_prompt(self) -> str:
        return self.llm.prompt if self.llm else ""


class MarkdownResponse(Response):
    media_type = "text/markdown"


class StreamMetadata(BaseModel):
    mimetype: str | None = Field(default=None, description="Mime type of the data")
    data_size: int | None = Field(default=None, description="Size of the data in bytes")
    last_modified: int | None = Field(
        default=None,
        description="Last modified timestamp(seconds) of the data",
    )


class ConvertResult(BaseModel):
    title: str | None = Field(default=None)
    markdown: str


class StorageResult(BaseModel):
    endpoint: str = Field(description="Storage endpoint")
    region: str = Field(description="Storage region")
    bucket: str = Field(description="Storage bucket")
    key: str = Field(description="Storage key")


class ConvertResponse(BaseModel):
    metadata: StreamMetadata | None = Field(
        default=None,
        description="Metadata of the data",
    )
    result: ConvertResult | None = Field(default=None, description="Converted result")
    storage: StorageResult | None = Field(
        default=None,
        description="Storage result",
    )
