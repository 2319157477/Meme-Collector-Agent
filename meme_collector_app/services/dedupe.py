"""Name normalization and duplicate checks."""

from __future__ import annotations

import re
import unicodedata

_DECORATION_RE = re.compile(r"[\s\-—_#《》<>【】\[\]（）()!！?？:：,，.。'\"“”‘’]")


def normalize_name(name: str) -> str:
    """Normalize names for conservative duplicate detection."""

    normalized = unicodedata.normalize("NFKC", name).casefold().strip()
    normalized = _DECORATION_RE.sub("", normalized)
    return normalized


def is_duplicate_name(name: str, existing_names: set[str]) -> bool:
    normalized = normalize_name(name)
    normalized_existing = {normalize_name(existing) for existing in existing_names}
    return normalized in normalized_existing
