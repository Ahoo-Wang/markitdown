import os
from typing import Optional

from openai import OpenAI
from pydantic import BaseModel, Field
from starlette.responses import Response

from markitdown import MarkItDown


class ConvertResult(BaseModel):
    title: Optional[str]
    markdown: str


class MarkdownResponse(Response):
    media_type = "text/markdown"


class LlmOptions(BaseModel):
    open_ai_base_url: str | None = Field(
        default=None, description="OpenAI API base URL"
    )
    open_ai_api_key: str | None = Field(default=None, description="OpenAI API key")
    model: str | None = Field(default=None, description="LLM model")
    prompt: str = ""


def is_blank(s: str) -> bool:
    return not s or s.isspace()


def blank_then_none(s: str) -> str | None:
    if is_blank(s):
        return None
    return s


def _build_markitdown(llm_options: Optional[LlmOptions] = None) -> MarkItDown:
    base_url = api_key = llm_model = prompt = None
    if llm_options:
        base_url = blank_then_none(llm_options.open_ai_base_url)
        api_key = blank_then_none(llm_options.open_ai_api_key)
        llm_model = blank_then_none(llm_options.model)
    if not llm_model:
        llm_model = blank_then_none(os.environ.get("LLM_MODEL"))
    llm_client = OpenAI(base_url=base_url, api_key=api_key)
    return MarkItDown(
        enable_plugins=True,
        enable_builtins=True,
        llm_client=llm_client,
        llm_model=llm_model,
    )
