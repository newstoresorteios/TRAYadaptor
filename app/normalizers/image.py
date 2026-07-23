from typing import Any


def normalize_images(raw: Any) -> list[dict[str, str | None]]:
    if isinstance(raw, (str, dict)):
        raw = [raw]
    result = []
    for item in raw or []:
        if isinstance(item, str):
            result.append({"url": item, "thumb_180": None})
            continue
        if not isinstance(item, dict):
            continue
        for wrapper in ("ProductImage", "VariantImage", "Image"):
            if isinstance(item.get(wrapper), dict):
                item = item[wrapper]
                break
        url_value = item.get("url")
        if isinstance(url_value, dict):
            url_value = url_value.get("https") or url_value.get("http")
        url = item.get("https") or item.get("http") or url_value
        thumbs = item.get("thumbs") if isinstance(item.get("thumbs"), dict) else {}
        thumb = thumbs.get("180") if isinstance(thumbs.get("180"), dict) else {}
        thumb_180 = thumb.get("https") or thumb.get("http")
        if url or thumb_180:
            result.append({"url": url, "thumb_180": thumb_180})
    return result


def primary_image_url(images: list[dict[str, Any]]) -> str | None:
    return next(
        (
            image.get("url") or image.get("thumb_180")
            for image in images
            if image.get("url") or image.get("thumb_180")
        ),
        None,
    )
