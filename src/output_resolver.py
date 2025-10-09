# src/output_resolver.py
import requests


def resolve_latest_path(base_outputs_url: str, timeout: float = 2.0) -> str:
    """
    Resolve which folder the server considers "latest".
    Fast path: HEAD /latest/ (works if a directory or symlink is exposed).
    Fallback: GET /latest.txt and return its trimmed contents.
    Final fallback: return "latest".
    """
    try:
        resp = requests.head(f"{base_outputs_url}/latest/", timeout=timeout)
        if resp.status_code in (200, 204, 304):
            return "latest"
    except requests.RequestException:
        pass

    try:
        resp = requests.get(f"{base_outputs_url}/latest.txt", timeout=timeout)
        if resp.ok:
            name = resp.text.strip()
            if name:
                return name
    except requests.RequestException:
        pass

    return "latest"
