"""Normalize image replies across SDKs without exposing binary data as text."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from core.llm_clients.adapter_protocol import value

MAX_IMAGE_BYTES = 10 * 1024 * 1024
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]\n]*\]\((?:<(?P<angle>[^>\n]+)>|(?P<plain>[^)\n]+))\)")


def markdown_images(text: str, *, source: str = "generated_image", cwd: Path | None = None) -> list[dict]:
    """Resolve explicit image Markdown in assistant output, leaving normal links alone."""
    images = []
    text = re.sub(r"```[\s\S]*?```|`[^`\n]*`", "", text)
    for match in _MARKDOWN_IMAGE.finditer(text):
        target = (match.group("angle") or match.group("plain")).strip()
        item = {"kind": "image", "source": source, "name": "generated-image"}
        if target.startswith("data:image/"):
            item["data_url"] = target
        elif urlsplit(target).scheme in {"https", "http"}:
            item["url"] = target
        else:
            path = Path(unquote(target))
            if not path.is_absolute():
                if cwd is None:
                    continue
                path = cwd / path
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif"}:
                continue
            try:
                if not path.is_file():
                    continue
            except OSError:
                continue
            item["path"] = str(path)
            item["name"] = path.name
        merge_images(images, [item])
    return images


def message_images(message: dict) -> list[str]:
    """Return input images with the legacy single-image field deduplicated."""
    images = list(message.get("images_base64") or [])
    legacy = message.get("image_base64")
    if legacy and legacy not in images:
        images.insert(0, legacy)
    return images


def image_data_url(encoded: str) -> str:
    """Keep the actual MIME type when replaying non-PNG attachments."""
    if encoded.startswith("data:image/"):
        return encoded
    from core.conversation_store.store import _image_suffix_and_mime
    try:
        header = base64.b64decode(encoded[:32])
    except ValueError:
        header = b""
    _suffix, mime = _image_suffix_and_mime(header)
    return f"data:{mime};base64,{encoded}"


def merge_images(target: list[dict], images: list[dict]) -> list[dict]:
    """Append unique images in provider order (including repeated stream events)."""
    def identity(item):
        raw = item.get("origin_url") or item.get("data_url") or item.get("path") or item.get("url") or ""
        return hashlib.sha256(str(raw).encode()).digest()

    seen = {identity(item) for item in target}
    for item in images:
        key = identity(item)
        if key not in seen:
            target.append(item)
            seen.add(key)
    return target


def extract_images(payload, *, source: str = "generated_image", cwd: Path | None = None) -> list[dict]:
    """Read explicit output image blocks, never tool arguments or input echoes."""
    images: list[dict] = []

    def visit(node):
        if isinstance(node, (list, tuple)):
            for child in node:
                visit(child)
            return
        if isinstance(node, str):
            merge_images(images, markdown_images(node, source=source, cwd=cwd))
            return
        if node is None or isinstance(node, (bytes, int, float, bool)):
            return
        kind = value(node, "type", "")
        if kind in {"text", "output_text"} or type(node).__name__ == "TextBlock":
            visit(value(node, "text", ""))
        inline = value(node, "inline_data") or value(node, "inlineData")
        source_block = value(node, "source") if kind == "image" else None
        image_format = value(node, "output_format") or "png"
        mime = value(node, "mime_type") or value(node, "media_type") or f"image/{image_format}"
        data = value(node, "b64_json")
        url = value(node, "data_url")
        path = value(node, "savedPath")
        if inline:
            mime = value(inline, "mime_type") or value(inline, "mimeType") or mime
            data = value(inline, "data")
        if source_block:
            mime = value(source_block, "media_type", mime)
            data = value(source_block, "data")
            url = value(source_block, "url") or url
        if kind in {"image", "image_url", "output_image"}:
            image_url = value(node, "image_url")
            url = (image_url if isinstance(image_url, str) else value(image_url, "url")) or value(node, "url") or url
            data = value(node, "data") or data
            path = value(node, "path") or path
        if kind in {"image_generation_call", "imageGeneration"}:
            result = value(node, "result")
            if isinstance(result, str):
                if result.startswith("data:"):
                    url = result
                elif not path:
                    data = result
        if isinstance(data, bytes):
            data = base64.b64encode(data).decode("ascii")
        if data and str(mime).startswith("image/"):
            url = f"data:{mime};base64,{data}"
        if path or url:
            item = {"kind": "image", "source": source, "name": value(node, "name") or "generated-image"}
            if path:
                item["path"] = str(path)
            elif str(url).startswith("data:image/"):
                item["data_url"] = str(url)
            elif urlsplit(str(url)).scheme in {"https", "http"}:
                item["url"] = str(url)
            else:
                item = None
            if item:
                merge_images(images, [item])
        # These are response containers, not arbitrary recursive JSON.
        for field in ("images", "content", "output", "parts", "candidates"):
            child = value(node, field)
            if child is not None and not isinstance(child, bytes):
                visit(child)
        for field in ("message", "delta", "item", "response"):
            child = value(node, field)
            if child is not None and not isinstance(child, (str, bytes)):
                visit(child)
        choices = value(node, "choices") or []
        if choices:
            visit(choices[0])

    visit(payload)
    return images


def materialize_images(images: list[dict]) -> list[dict]:
    """Fetch remote outputs on the model worker, before UI persistence."""
    result = []
    for raw in images:
        item = dict(raw)
        url = item.pop("url", "")
        if url:
            import httpx

            # Do not forward provider credentials or follow arbitrary redirects.
            with httpx.stream("GET", url, timeout=30, follow_redirects=False) as response:
                response.raise_for_status()
                mime = response.headers.get("content-type", "image/png").split(";", 1)[0]
                if not mime.startswith("image/"):
                    raise ValueError("Provider image URL did not return an image")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_IMAGE_BYTES:
                        raise ValueError("Provider image exceeds the attachment size limit")
            item["data_url"] = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
            item["origin_url"] = url
        result.append(item)
    return result


class ImageOutputChunk(str):
    """A nonempty stream item so image-only replies also stop route fallback."""
    kind = "attachments"

    def __new__(cls, images: list[dict]):
        return super().__new__(cls, json.dumps(materialize_images(images), separators=(",", ":")))


class ImageReplyText(str):
    """Keep blocking APIs string-compatible while retaining image output."""
    images: list[dict]
    def __new__(cls, text: str, images: list[dict]):
        instance = super().__new__(cls, text)
        instance.images = images
        return instance


def reply_chunks(text):
    if getattr(text, "images", None):
        yield ImageOutputChunk(text.images)
    if text:
        yield str(text)
