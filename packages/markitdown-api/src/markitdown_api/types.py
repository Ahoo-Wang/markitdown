from typing import Optional
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


class ConvertRequest(BaseModel):
    llm: LlmOptions | None = Field(default=None, description="LLM options")


class MarkdownResponse(Response):
    media_type = "text/markdown"


class ConvertResult(BaseModel):
    title: Optional[str]
    markdown: str
