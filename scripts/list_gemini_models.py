"""List the Gemini models this API key can call (generateContent), newest names first.

    uv run python scripts/list_gemini_models.py

Reads GEMINI_API_KEY from the environment or .env. Prints model names only, never the key.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from agentmaxxing.llm import GEMINI_BASE, read_env_key

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    key = read_env_key("GEMINI_API_KEY", ROOT / ".env")
    if not key:
        print("GEMINI_API_KEY is not set (environment or .env)", file=sys.stderr)
        return 1
    names: list[str] = []
    token = ""
    while True:
        url = f"{GEMINI_BASE}/models?pageSize=200" + (f"&pageToken={token}" if token else "")
        request = urllib.request.Request(url, headers={"x-goog-api-key": key})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace").replace(key, "[REDACTED]")
            print(f"HTTP {exc.code}: {body[:300]}", file=sys.stderr)
            return 1
        for model in data.get("models", []):
            if "generateContent" in model.get("supportedGenerationMethods", []):
                names.append(str(model["name"]).removeprefix("models/"))
        token = data.get("nextPageToken", "")
        if not token:
            break
    for name in sorted(names, reverse=True):
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
