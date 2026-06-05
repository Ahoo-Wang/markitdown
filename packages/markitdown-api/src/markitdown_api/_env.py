import os


FALSE_VALUES = {"0", "false", "no", "off"}
KEEP_DATA_URIS_ENV = "MARKITDOWN_API_KEEP_DATA_URIS"


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in FALSE_VALUES


def default_keep_data_uris() -> bool:
    return env_bool(KEEP_DATA_URIS_ENV, False)
