def call_http_get(url: str, params: dict | None = None) -> dict:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests package is required for HTTP tools") from exc

    resp = requests.get(url, params=params, timeout=5)
    resp.raise_for_status()
    return resp.json()


def call_http_post(url: str, data: dict | None = None, json_body: dict | None = None) -> dict:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("requests package is required for HTTP tools") from exc

    resp = requests.post(url, data=data, json=json_body, timeout=5)
    resp.raise_for_status()
    return resp.json()
