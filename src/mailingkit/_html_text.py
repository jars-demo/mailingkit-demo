"""A small, dependency-free HTML to plain text converter for the text part of an email."""

from __future__ import annotations

import re
from html.parser import HTMLParser

_SKIP = {"head", "script", "style", "title"}
_BLOCK = {
    "address", "article", "aside", "blockquote", "div", "footer", "h1", "h2", "h3", "h4", "h5",
    "h6", "header", "hr", "main", "nav", "ol", "p", "section", "table", "tr", "ul",
}  # fmt: skip
_SPACES = re.compile(r"[ \t\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._links: list[tuple[str | None, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip_depth += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCK:
            self.parts.append("\n\n")
        elif tag == "td":
            self.parts.append(" ")
        elif tag == "a":
            self._links.append((dict(attrs).get("href"), len(self.parts)))

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK:
            self.parts.append("\n\n")
        elif tag == "a" and self._links:
            href, start = self._links.pop()
            label = "".join(self.parts[start:]).strip()
            if href and href.startswith(("http://", "https://")) and href != label:
                self.parts.append(f" ({href})")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(_SPACES.sub(" ", data.replace("\n", " ")))


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    lines = (line.strip() for line in "".join(parser.parts).splitlines())
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
