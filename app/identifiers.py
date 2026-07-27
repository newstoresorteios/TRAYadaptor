from typing import Any


def normalize_optional_variant_id(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("variant identifier must be a positive integer or absent")
    text = str(value).strip()
    if text in {"", "0"}:
        return None
    if not text.isascii() or not text.isdecimal() or int(text) < 1:
        raise ValueError("variant identifier must be a positive integer or absent")
    return int(text)