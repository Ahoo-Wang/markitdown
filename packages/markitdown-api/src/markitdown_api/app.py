from fastapi import FastAPI
from requests import HTTPError
from starlette.requests import Request
from starlette.responses import JSONResponse

from markitdown.__about__ import __version__ as markitdown_version
from markitdown_api import convert_uri, convert_text, convert_file, __about__

app = FastAPI(
    title="MarkItDown API",
    description="""A simple API for converting various files to Markdown format.
    Currently supports the conversion from:
    PDF,PowerPoint,Word,Excel,
    Images (EXIF metadata and OCR),Audio (EXIF metadata and speech transcription),HTML,
    Text-based formats (CSV, JSON, XML),ZIP files (iterates over contents),Youtube URLs,EPubs and more!
    """,
    version=markitdown_version + "-" + __about__.__version__,
    contact={
        "name": "Ahoo Wang",
        "url": "https://github.com/Ahoo-Wang",
        "email": "ahoowang@qq.com",
    },
)

app.include_router(convert_uri.router)
app.include_router(convert_text.router)
app.include_router(convert_file.router)


async def file_not_found_handler(request: Request, exc: FileNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


async def http_error_handler(request: Request, exc: HTTPError):
    return JSONResponse(
        status_code=exc.response.status_code, content={"detail": str(exc)}
    )


async def type_error_handler(request: Request, exc: TypeError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


async def key_error_handler(request: Request, exc: KeyError):
    return JSONResponse(
        status_code=400, content={"detail": f"Missing required field: {str(exc)}"}
    )


async def index_error_handler(request: Request, exc: IndexError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": str(exc)})


app.add_exception_handler(FileNotFoundError, file_not_found_handler)
app.add_exception_handler(ValueError, value_error_handler)
app.add_exception_handler(HTTPError, http_error_handler)
app.add_exception_handler(TypeError, type_error_handler)
app.add_exception_handler(KeyError, key_error_handler)
app.add_exception_handler(IndexError, index_error_handler)
app.add_exception_handler(Exception, global_exception_handler)
