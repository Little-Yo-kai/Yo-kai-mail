"""Deterministic plain text from the final HTML, shared by every send path."""

import re
from html.parser import HTMLParser
from urllib.parse import urlparse


class _EmailTextParser(HTMLParser):
    BLOCK_TAGS = frozenset({
        "address", "article", "blockquote", "div", "footer", "h1", "h2",
        "h3", "h4", "h5", "h6", "header", "li", "p", "section", "tr",
    })
    IGNORED_TAGS = frozenset({"head", "script", "style", "template", "noscript"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0
        self.links: list[tuple[str, int]] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORED_TAGS:
            self.ignored_depth += 1
        if self.ignored_depth:
            return
        attributes = dict(attrs)
        if tag in self.BLOCK_TAGS or tag == "br":
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")
        elif tag == "td":
            self.parts.append(" ")
        elif tag == "img" and attributes.get("alt"):
            self.parts.append(f" {attributes['alt']} ")
        elif tag == "a":
            href = attributes.get("href") or ""
            # Preserve useful CTA/unsubscribe destinations; discard script URLs.
            try:
                scheme = urlparse(href).scheme.lower()
            except ValueError:
                scheme = ""
            if scheme not in {"http", "https", "mailto", "tel"}:
                href = ""
            self.links.append((href, len(self.parts)))

    def handle_endtag(self, tag):
        if tag in self.IGNORED_TAGS:
            self.ignored_depth = max(0, self.ignored_depth - 1)
            return
        if self.ignored_depth:
            return
        if tag == "a" and self.links:
            href, start = self.links.pop()
            label = "".join(self.parts[start:]).strip()
            if href and href not in {label, f"mailto:{label}", f"tel:{label}"}:
                self.parts.append(f" ({href})")
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.ignored_depth:
            self.parts.append(data)


def html_to_plain_text(html_document: str) -> str:
    parser = _EmailTextParser()
    parser.feed(html_document)
    parser.close()
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
