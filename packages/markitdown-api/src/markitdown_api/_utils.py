from email.utils import parsedate_to_datetime
from requests.utils import CaseInsensitiveDict


def _parse_mime_type_from_content_type(content_type: str) -> str | None:
    if not content_type:
        return None

    parts = content_type.split(";")
    return parts.pop(0).strip()


def _parse_last_modified_timestamp(headers: CaseInsensitiveDict[str]) -> int | None:
    last_modified_str = headers.get("Last-Modified")
    if not last_modified_str:
        return None
    last_modified = parsedate_to_datetime(last_modified_str)
    return int(last_modified.timestamp())


YUQUE_API_PATH = "yuque.com/api/docs"


def is_yuque_api_url(url: str) -> bool:
    return YUQUE_API_PATH in url
