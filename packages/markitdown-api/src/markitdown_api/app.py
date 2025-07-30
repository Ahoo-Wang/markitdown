from fastapi import FastAPI
from requests import HTTPError
from starlette.requests import Request
from starlette.responses import JSONResponse
import logging

from markitdown import FileConversionException
from markitdown.__about__ import __version__ as markitdown_version
from markitdown_api import (
    convert_uri,
    convert_text,
    convert_file,
    convert_http,
    __about__,
    convert_yuque_api,
)

# 配置日志记录器
logger = logging.getLogger(__name__)

app = FastAPI(
    title="MarkItDown API",
    description="""A simple API for converting various files to Markdown format.
    Currently supports the conversion from:
    PDF,PowerPoint,Word,Excel,
    Images (EXIF metadata and OCR),Audio (EXIF metadata and speech transcription),HTML,
    Text-based formats (CSV, JSON, XML),ZIP files (iterates over contents),Youtube URLs,EPubs and more!
    """,
    version=markitdown_version + "-" + __about__.__version__,
    contact={"name": "Ahoo Wang", "url": "https://github.com/Ahoo-Wang/markitdown"},
)

app.include_router(convert_uri.router)
app.include_router(convert_text.router)
app.include_router(convert_file.router)
app.include_router(convert_http.router)
app.include_router(convert_yuque_api.router)


def __error_content(exc: Exception):
    return {"detail": str(exc)}


async def file_not_found_handler(request: Request, exc: FileNotFoundError):
    logger.warning(f"File not found: {str(exc)}", exc_info=True)
    return JSONResponse(status_code=404, content=__error_content(exc))


async def value_error_handler(request: Request, exc: ValueError):
    logger.warning(f"Value error: {str(exc)}", exc_info=True)
    return JSONResponse(status_code=400, content=__error_content(exc))


async def http_error_handler(request: Request, exc: HTTPError):
    logger.warning(f"HTTP error: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=exc.response.status_code, content=__error_content(exc)
    )


async def type_error_handler(request: Request, exc: TypeError):
    logger.warning(f"Type error: {str(exc)}", exc_info=True)
    return JSONResponse(status_code=400, content=__error_content(exc))


async def key_error_handler(request: Request, exc: KeyError):
    logger.warning(f"Key error: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=400, content={"detail": f"Missing required field: {str(exc)}"}
    )


async def file_conversion_handler(request: Request, exc: FileConversionException):
    logger.warning(f"File conversion error: {str(exc)}", exc_info=True)
    return JSONResponse(status_code=400, content=__error_content(exc))


async def index_error_handler(request: Request, exc: IndexError):
    logger.warning(f"Index error: {str(exc)}", exc_info=True)
    return JSONResponse(status_code=400, content=__error_content(exc))


async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unexpected error: {str(exc)}", exc_info=True)
    return JSONResponse(status_code=500, content=__error_content(exc))


app.add_exception_handler(FileNotFoundError, file_not_found_handler)
app.add_exception_handler(ValueError, value_error_handler)
app.add_exception_handler(HTTPError, http_error_handler)
app.add_exception_handler(TypeError, type_error_handler)
app.add_exception_handler(KeyError, key_error_handler)
app.add_exception_handler(IndexError, index_error_handler)
app.add_exception_handler(FileConversionException, file_conversion_handler)
app.add_exception_handler(Exception, global_exception_handler)
