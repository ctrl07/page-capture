"""Import URLs from CSV files, or manual input."""

from __future__ import annotations

import csv
import io
import re
from urllib.parse import urlparse

__all__ = [
    "import_from_csv_file",
    "parse_urls_text",
    "is_valid_url",
]


def is_valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parsed.scheme in ("http", "https") and parsed.netloc)


def parse_urls_text(raw: str) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for token in re.split(r"[,\s]+", line):
            token = token.strip()
            if not token or token.startswith("#"):
                continue
            if token not in seen:
                seen.add(token)
                cleaned.append(token)
    return cleaned


def import_from_csv_file(content: str | bytes) -> list[tuple[str, str | None]]:
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return []

    pairs: list[tuple[str, str | None]] = []

    for row in rows:
        if not row:
            continue
        a = (row[0] or "").strip().strip('"')
        if not is_valid_url(a):
            continue
        b = (row[1] or "").strip().strip('"') if len(row) > 1 else ""
        if b and is_valid_url(b):
            pairs.append((a, b))
        else:
            pairs.append((a, None))

    return pairs
