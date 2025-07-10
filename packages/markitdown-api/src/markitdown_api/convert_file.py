from io import BufferedReader
from typing import Annotated, Any

from fastapi import APIRouter, UploadFile, File, Form

from markitdown import StreamInfo
from markitdown_api.api_converter import ApiConverter
from markitdown_api.api_types import (
    ConvertResult,
    LlmOptions,
    MarkdownResponse,
    ConvertRequest,
    ConvertResponse,
    StreamMetadata,
)
from markitdown_api.convert_http import _parse_mime_type_from_content_type

TAG = "Convert File"

router = APIRouter(
    prefix="/convert/file",
    tags=[TAG],
)


class ConvertFileRequest(ConvertRequest):
    file: UploadFile


class FileApiConverter(ApiConverter):
    def __init__(self, request: ConvertFileRequest):
        super().__init__(request)

    def _internal_convert(self, **kwargs: Any) -> ConvertResult:
        self.metadata = StreamMetadata(
            data_size=self.request.file.size,
            mimetype=_parse_mime_type_from_content_type(self.request.file.content_type),
        )
        stream_info = StreamInfo(
            mimetype=self.metadata.mimetype, filename=self.request.file.filename
        )
        with BufferedReader(self.request.file.file) as buffered_reader:
            convert_result = self.markitdown.convert_stream(
                buffered_reader, stream_info=stream_info, **kwargs
            )
            return ConvertResult(
                title=convert_result.title, markdown=convert_result.markdown
            )


@router.post(path="", response_model=ConvertResponse)
async def convert_file(
    file: Annotated[UploadFile, File()],
    openai_base_url: Annotated[str, Form()] = "",
    openai_api_key: Annotated[str, Form()] = "",
    llm_model: Annotated[str, Form()] = "",
    llm_prompt: Annotated[str, Form()] = "",
    keep_data_uris: Annotated[bool, Form()] = False,
):
    return FileApiConverter(
        ConvertFileRequest(
            file=file,
            keep_data_uris=keep_data_uris,
            llm=LlmOptions(
                model=llm_model,
                open_ai_api_key=openai_api_key,
                open_ai_base_url=openai_base_url,
                prompt=llm_prompt,
            ),
        )
    ).convert()


@router.post(path="/markdown", response_class=MarkdownResponse)
async def convert_file_markdown(
    file: Annotated[UploadFile, File()],
    openai_base_url: Annotated[str, Form()] = "",
    openai_api_key: Annotated[str, Form()] = "",
    llm_model: Annotated[str, Form()] = "",
    llm_prompt: Annotated[str, Form()] = "",
    keep_data_uris: Annotated[bool, Form()] = False,
):
    return (
        FileApiConverter(
            ConvertFileRequest(
                file=file,
                keep_data_uris=keep_data_uris,
                llm=LlmOptions(
                    model=llm_model,
                    open_ai_api_key=openai_api_key,
                    open_ai_base_url=openai_base_url,
                    prompt=llm_prompt,
                ),
            )
        )
        .convert()
        .result.markdown
    )
