import requests


def call_http_get(url: str, params: dict | None = None) -> dict:
    resp = requests.get(url, params=params, timeout=5)
    resp.raise_for_status()
    return resp.json()
