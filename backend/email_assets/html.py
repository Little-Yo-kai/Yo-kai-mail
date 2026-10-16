import html
import re

IMAGE_TAG_PATTERN = re.compile(
    r'''<img\b(?:[^>"']|"[^"]*"|'[^']*')*>''', re.IGNORECASE,
)
ATTRIBUTE_PATTERN = re.compile(
    r'''\s+([^\s"'<>/=`]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'<>`]+)))?''',
)


def image_source_spans(document: str):
    """Yield actual image src values and their spans without reserializing HTML."""
    for tag_match in IMAGE_TAG_PATTERN.finditer(document):
        for attribute in ATTRIBUTE_PATTERN.finditer(tag_match.group(0)):
            if attribute.group(1).lower() != "src":
                continue
            for group in (2, 3, 4):
                if attribute.group(group) is not None:
                    start, end = attribute.span(group)
                    yield (
                        tag_match.start() + start,
                        tag_match.start() + end,
                        html.unescape(attribute.group(group)),
                    )
                    break


def image_sources(document: str) -> set[str]:
    return {source for _, _, source in image_source_spans(document)}


def replace_image_sources(document: str, replacements: dict[str, str]) -> str:
    parts: list[str] = []
    cursor = 0
    for start, end, source in image_source_spans(document):
        replacement = replacements.get(source)
        if replacement is None:
            continue
        parts.extend((document[cursor:start], html.escape(replacement, quote=True)))
        cursor = end
    parts.append(document[cursor:])
    return "".join(parts)
