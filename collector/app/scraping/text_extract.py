"""Clean page text for storage / scoring (no nav/footer/script noise)."""

from __future__ import annotations

import re
from typing import Any

_WS_RE = re.compile(r"[ \t]+")
_BLANK_RE = re.compile(r"\n{3,}")

_STRIP_TAGS: tuple[str, ...] = (
    "script",
    "style",
    "noscript",
    "svg",
    "iframe",
    "nav",
    "footer",
    "header",
    "aside",
)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def extract_title(response: Any) -> str:
    title = response.css("title::text").get()
    if title:
        return _as_text(title).strip()
    og = response.css("meta[property='og:title']::attr(content)").get()
    return _as_text(og).strip() if og else ""


def _first_node(response: Any, selectors: tuple[str, ...]) -> Any:
    for sel in selectors:
        nodes = response.css(sel)
        if nodes:
            try:
                return nodes[0]
            except (IndexError, TypeError, AttributeError):
                continue
    return response


def extract_main_text(response: Any, *, max_chars: int) -> str:
    """Prefer main/article content; strip chrome tags; truncate safely."""
    node = _first_node(response, ("main", "article", "[role='main']", "body"))
    raw = ""
    if hasattr(node, "get_all_text"):
        raw = _as_text(
            node.get_all_text(
                separator="\n",
                strip=True,
                ignore_tags=_STRIP_TAGS,
            )
        )
    cleaned_lines = [_WS_RE.sub(" ", line).strip() for line in raw.splitlines()]
    cleaned = _BLANK_RE.sub("\n\n", "\n".join(line for line in cleaned_lines if line)).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    truncated = cleaned[:max_chars]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated.rstrip() + "…"


def extract_link_hints(response: Any, *, limit: int = 40) -> list[str]:
    texts: list[str] = []
    for node in response.css("a"):
        text = _as_text(node.css("::text").get()).strip()
        if not text:
            text = _as_text(node.css("::attr(href)").get()).strip()
        if text:
            texts.append(text[:120])
        if len(texts) >= limit:
            break
    return texts


def extract_anchors(response: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for node in response.css("a"):
        href = node.css("::attr(href)").get()
        if not href:
            continue
        text = _as_text(node.css("::text").get()).strip()
        out.append((str(href), text))
    return out
