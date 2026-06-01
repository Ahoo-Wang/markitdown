import os
from typing import Optional

from openai import OpenAI

from markitdown import MarkItDown
from markitdown_api.api_types import LlmOptions, ConvertRequest


def is_blank(s: str) -> bool:
    return not s or s.isspace()


def blank_then_none(s: str) -> str | None:
    if is_blank(s):
        return None
    return s


def _build_markitdown(llm_options: Optional[LlmOptions] = None) -> MarkItDown:
    base_url = api_key = llm_client = llm_model = llm_prompt = None
    if llm_options:
        base_url = blank_then_none(llm_options.open_ai_base_url)
        api_key = blank_then_none(llm_options.open_ai_api_key)
        llm_model = blank_then_none(llm_options.model)
        llm_prompt = blank_then_none(llm_options.prompt)
    if not llm_model:
        llm_model = blank_then_none(os.environ.get("LLM_MODEL"))

    api_key = os.environ.get("OPENAI_API_KEY", api_key)
    if api_key:
        llm_client = OpenAI(base_url=base_url, api_key=api_key)

    markitdown = MarkItDown(
        enable_plugins=True,
        enable_builtins=True,
        llm_client=llm_client,
        llm_model=llm_model,
        llm_prompt=llm_prompt,
    )
    return markitdown


def build_markitdown(request: ConvertRequest) -> MarkItDown:
    markitdown = _build_markitdown(request.llm)
    converter_options = request.converter
    if not converter_options:
        return markitdown

    for converter in converter_options.exclude:
        markitdown.unregister_converter(converter)
    return markitdown
