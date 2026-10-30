"""Split pages into chunks of about 1,200 characters, by report section.

A chunk never crosses a page, so the page number on a citation is always right. A line is never cut
unless it alone is too long, so a table row stays whole.
"""

import re
from dataclasses import dataclass

from sahyog.ingest.parse import PageText

MAX_CHARS = 1200
_HEADING = re.compile(r"^[A-Z][A-Z &/,-]{3,}:?$")


@dataclass(frozen=True)
class Chunk:
    page: int
    text: str
    source: str
    confidence: float | None


def chunk_pages(pages: list[PageText]) -> list[Chunk]:
    return [c for p in pages for c in _chunk_page(p)]


def _chunk_page(page: PageText) -> list[Chunk]:
    parts: list[str] = []
    current: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal current, size
        if current:
            parts.append("\n".join(current))
        current, size = [], 0

    for line in (ln.strip() for ln in page.text.splitlines()):
        if not line:
            continue
        for piece in _pieces(line):
            if _HEADING.match(piece) and size > MAX_CHARS // 4:
                flush()
            if size + len(piece) + 1 > MAX_CHARS:
                flush()
            current.append(piece)
            size += len(piece) + 1
    flush()
    return [Chunk(page.page, text, page.source, page.confidence) for text in parts]


def _pieces(line: str) -> list[str]:
    if len(line) <= MAX_CHARS:
        return [line]
    return [line[i : i + MAX_CHARS] for i in range(0, len(line), MAX_CHARS)]
