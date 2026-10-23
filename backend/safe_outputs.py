"""Public output boundaries: never serialize exception bodies or credential URLs."""
from urllib.parse import urlsplit

TOOL_ERROR = "数据获取失败，请稍后重试。"
PDF_ERROR = "PDF 下载失败，请稍后重试。"


def public_error(kind="tool"):
    return PDF_ERROR if kind == "pdf" else TOOL_ERROR


def safe_tool_data(value):
    if isinstance(value, dict):
        return {key: (TOOL_ERROR if item else item)
                if key in {"error", "err", "errors", "fetch_error"}
                else safe_tool_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_tool_data(item) for item in value]
    return value


def safe_url_origin(url):
    """Rebuild, never echo netloc: legacy userinfo/query/path are not public."""
    try:
        parsed = urlsplit(str(url or ""))
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            return ""
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{host}{port}"
    except ValueError:
        return ""
