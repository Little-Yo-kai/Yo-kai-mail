import html
import re

IMAGE_SOURCE = re.compile(
    r"(<img\b[^>]*?\s+src\s*=\s*)([\"'])(.*?)\2", re.IGNORECASE | re.DOTALL
)


def image_sources(document: str) -> set[str]:
    return {html.unescape(match.group(3)) for match in IMAGE_SOURCE.finditer(document)}


def replace_image_sources(document: str, replacements: dict[str, str]) -> str:
    def replace(match):
        replacement = replacements.get(html.unescape(match.group(3)))
        if replacement is None:
            return match.group(0)
        quote = match.group(2)
        return f"{match.group(1)}{quote}{html.escape(replacement, quote=True)}{quote}"

    return IMAGE_SOURCE.sub(replace, document)
