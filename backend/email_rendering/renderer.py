from html import escape
from urllib.parse import urlparse

from brand_intelligence.schemas import BrandProfile
from email_generation.schemas import AssetDescriptor, EmailDesign, EmailSection


SYSTEM_FONT = "Arial, Helvetica, sans-serif"

CONTENT_WIDTHS = {
    "narrow": "520px",
    "standard": "600px",
    "wide": "680px",
}

SECTION_PADDING = {
    "compact": "16px 24px",
    "balanced": "28px 32px",
    "generous": "44px 36px",
    "very_generous": "64px 36px",
}


class EmailRenderInputError(ValueError):
    pass


def _safe_text(value: str | None) -> str:
    return escape(value or "", quote=False)


def _safe_attr(value: str | None) -> str:
    return escape(value or "", quote=True)


def _safe_url(value: str | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None

    candidate = value.strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    return candidate


def _first_nonempty(*values: str | None) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_font(value: str | None) -> str:
    value = _first_nonempty(value)
    if not value:
        return SYSTEM_FONT
    return value[:200]


def _normalize_hex(value: str | None, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback

    value = value.strip()
    if len(value) in {4, 7} and value.startswith("#"):
        chars = value[1:]
        if all(char in "0123456789abcdefABCDEF" for char in chars):
            return value.upper()

    return fallback


def _contrast_text(hex_color: str) -> str:
    value = hex_color.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)

    try:
        red = int(value[0:2], 16)
        green = int(value[2:4], 16)
        blue = int(value[4:6], 16)
    except (ValueError, IndexError):
        return "#FFFFFF"

    luminance = (
        0.2126 * red
        + 0.7152 * green
        + 0.0722 * blue
    )
    return "#111111" if luminance > 170 else "#FFFFFF"


def resolve_theme(brand: BrandProfile, design: EmailDesign) -> dict:
    colors = brand.visual.colors
    is_dark = brand.visual.color_scheme == "dark"

    text_primary = _normalize_hex(
        colors.text_primary,
        "#F5F5F5" if is_dark else "#1A1A1A",
    )
    primary = _normalize_hex(
        colors.primary,
        text_primary,
    )
    secondary = _normalize_hex(
        colors.secondary,
        "#8A8A8A",
    )
    accent = _normalize_hex(
        colors.accent,
        primary,
    )
    background = _normalize_hex(
        colors.background,
        "#111111" if is_dark else "#FFFFFF",
    )
    neutral = "#1F1F1F" if is_dark else "#F5F5F5"

    color_roles = {
        "primary": primary,
        "secondary": secondary,
        "accent": accent,
        "background": background,
        "text_primary": text_primary,
        "neutral": neutral,
    }

    heading_family = _normalize_font(
        brand.visual.typography.heading_family
    )
    body_family = _normalize_font(
        _first_nonempty(
            brand.visual.typography.body_family,
            brand.visual.typography.heading_family,
        )
    )

    font_roles = {
        "brand_heading": heading_family,
        "brand_body": body_family,
        "system": SYSTEM_FONT,
    }

    primary_color = color_roles[design.theme.primary_color_role]
    background_color = color_roles[design.theme.background_color_role]
    button_color = color_roles[design.theme.button_color_role]

    return {
        "content_width": CONTENT_WIDTHS[design.theme.content_width],
        "heading_font": font_roles[design.theme.heading_font_role],
        "body_font": font_roles[design.theme.body_font_role],
        "primary_color": primary_color,
        "background_color": background_color,
        "text_color": text_primary,
        "secondary_color": secondary,
        "accent_color": accent,
        "neutral_color": neutral,
        "button_color": button_color,
        "button_text_color": _contrast_text(button_color),
        "color_roles": color_roles,
    }


def _section_background(section: EmailSection, theme: dict) -> str:
    role = section.style.background_role
    if role in {"transparent", "brand_background", "image"}:
        return theme["background_color"]
    return theme["color_roles"].get(role, theme["background_color"])


def _asset_map(assets: list[AssetDescriptor]) -> dict[str, str]:
    result: dict[str, str] = {}
    for asset in assets:
        safe_url = _safe_url(asset.url)
        if safe_url:
            result[asset.asset_id] = safe_url
    return result


def _mj_text(
    value: str | None,
    *,
    align: str,
    font_family: str,
    color: str,
    font_size: str = "16px",
    line_height: str = "24px",
    font_weight: str = "400",
    padding: str = "0px",
    letter_spacing: str | None = None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""

    letter_attr = (
        f' letter-spacing="{_safe_attr(letter_spacing)}"'
        if letter_spacing
        else ""
    )
    return (
        f'<mj-text align="{_safe_attr(align)}" '
        f'font-family="{_safe_attr(font_family)}" '
        f'color="{_safe_attr(color)}" '
        f'font-size="{_safe_attr(font_size)}" '
        f'line-height="{_safe_attr(line_height)}" '
        f'font-weight="{_safe_attr(font_weight)}" '
        f'padding="{_safe_attr(padding)}"{letter_attr}>'
        f'{_safe_text(value)}</mj-text>'
    )


def _mj_button(cta, *, align: str, theme: dict) -> str:
    if cta is None:
        return ""

    href = _safe_url(cta.url)
    if not href:
        return ""

    return (
        f'<mj-button align="{_safe_attr(align)}" '
        f'href="{_safe_attr(href)}" '
        f'background-color="{_safe_attr(theme["button_color"])}" '
        f'color="{_safe_attr(theme["button_text_color"])}" '
        f'font-family="{_safe_attr(theme["body_font"])}" '
        'font-size="14px" font-weight="500" '
        'border-radius="0px" inner-padding="13px 24px" '
        'padding="22px 0 0 0">'
        f'{_safe_text(cta.label)}</mj-button>'
    )


def _mj_image(
    asset_id: str | None,
    *,
    asset_urls: dict[str, str],
    alt: str | None,
    padding: str = "0px",
) -> str:
    if not asset_id:
        return ""

    src = asset_urls.get(asset_id)
    if not src:
        return ""

    return (
        f'<mj-image src="{_safe_attr(src)}" '
        f'alt="{_safe_attr(alt or "")}" '
        f'padding="{_safe_attr(padding)}" fluid-on-mobile="true" />'
    )


def _section_copy(section: EmailSection, theme: dict) -> str:
    align = section.style.alignment
    parts = [
        _mj_text(
            section.eyebrow,
            align=align,
            font_family=theme["body_font"],
            color=theme["secondary_color"],
            font_size="11px",
            line_height="16px",
            font_weight="600",
            padding="0 0 12px 0",
            letter_spacing="1.8px",
        ),
        _mj_text(
            section.headline,
            align=align,
            font_family=theme["heading_font"],
            color=theme["text_color"],
            font_size="30px" if section.type != "hero" else "38px",
            line_height="38px" if section.type != "hero" else "46px",
            font_weight="500",
            padding="0 0 14px 0",
        ),
        _mj_text(
            section.body,
            align=align,
            font_family=theme["body_font"],
            color=theme["text_color"],
            font_size="15px",
            line_height="24px",
            padding="0px",
        ),
        _mj_button(section.cta, align=align, theme=theme),
    ]
    return "".join(part for part in parts if part)


def _render_item(item, *, theme: dict, asset_urls: dict[str, str]) -> str:
    parts = [
        _mj_image(
            item.asset_id,
            asset_urls=asset_urls,
            alt=item.title,
            padding="0 0 18px 0",
        ),
        _mj_text(
            item.title,
            align="center",
            font_family=theme["heading_font"],
            color=theme["text_color"],
            font_size="18px",
            line_height="24px",
            font_weight="500",
            padding="0 0 8px 0",
        ),
        _mj_text(
            item.body,
            align="center",
            font_family=theme["body_font"],
            color=theme["text_color"],
            font_size="14px",
            line_height="22px",
        ),
        _mj_button(item.cta, align="center", theme=theme),
    ]
    return "".join(part for part in parts if part)


def _render_grid(section: EmailSection, *, theme: dict, asset_urls: dict[str, str]) -> str:
    background = _section_background(section, theme)
    padding = SECTION_PADDING[section.style.spacing]
    columns = []

    for item in section.items:
        columns.append(
            '<mj-column padding="8px">'
            + _render_item(item, theme=theme, asset_urls=asset_urls)
            + '</mj-column>'
        )

    return (
        f'<mj-section background-color="{_safe_attr(background)}" '
        f'padding="{_safe_attr(padding)}">'
        + "".join(columns)
        + '</mj-section>'
    )


def _render_split(section: EmailSection, *, theme: dict, asset_urls: dict[str, str]) -> str:
    background = _section_background(section, theme)
    padding = SECTION_PADDING[section.style.spacing]
    asset_id = section.asset_ids[0] if section.asset_ids else None
    image_column = (
        '<mj-column width="50%" padding="0 18px">'
        + _mj_image(
            asset_id,
            asset_urls=asset_urls,
            alt=section.headline,
        )
        + '</mj-column>'
    )
    copy_column = (
        '<mj-column width="50%" padding="0 18px">'
        + _section_copy(section, theme)
        + '</mj-column>'
    )

    columns = (
        copy_column + image_column
        if section.layout == "split_image_right"
        else image_column + copy_column
    )

    return (
        f'<mj-section background-color="{_safe_attr(background)}" '
        f'padding="{_safe_attr(padding)}">'
        f'{columns}</mj-section>'
    )


def _render_standard(section: EmailSection, *, theme: dict, asset_urls: dict[str, str]) -> str:
    background = _section_background(section, theme)
    padding = SECTION_PADDING[section.style.spacing]
    asset_id = section.asset_ids[0] if section.asset_ids else None

    image = _mj_image(
        asset_id,
        asset_urls=asset_urls,
        alt=section.headline,
        padding="0 0 28px 0",
    )

    content = image + _section_copy(section, theme)

    if section.items:
        item_parts = [
            '<mj-spacer height="18px" />',
            *[
                _render_item(
                    item,
                    theme=theme,
                    asset_urls=asset_urls,
                )
                for item in section.items
            ],
        ]
        content += "".join(item_parts)

    return (
        f'<mj-section background-color="{_safe_attr(background)}" '
        f'padding="{_safe_attr(padding)}">'
        f'<mj-column>{content}</mj-column>'
        '</mj-section>'
    )


def _render_section(section: EmailSection, *, theme: dict, asset_urls: dict[str, str]) -> str:
    if section.type == "divider":
        background = _section_background(section, theme)
        return (
            f'<mj-section background-color="{_safe_attr(background)}" '
            'padding="12px 36px">'
            '<mj-column>'
            f'<mj-divider border-color="{_safe_attr(theme["secondary_color"])}" '
            'border-width="1px" padding="0px" />'
            '</mj-column></mj-section>'
        )

    if section.type == "product_grid" or section.layout in {"grid_2", "grid_3"}:
        return _render_grid(
            section,
            theme=theme,
            asset_urls=asset_urls,
        )

    if section.layout in {"split_image_left", "split_image_right"} and section.asset_ids:
        return _render_split(
            section,
            theme=theme,
            asset_urls=asset_urls,
        )

    return _render_standard(
        section,
        theme=theme,
        asset_urls=asset_urls,
    )


def render_email_to_mjml(
    *,
    brand_profile: dict,
    email_design: dict,
    asset_inventory: list[dict] | None = None,
) -> dict:
    try:
        brand = BrandProfile.model_validate(brand_profile)
        design = EmailDesign.model_validate(email_design)
        assets = [
            AssetDescriptor.model_validate(item)
            for item in (asset_inventory or [])
        ]
    except Exception as exc:
        raise EmailRenderInputError(str(exc)) from exc

    theme = resolve_theme(brand, design)
    asset_urls = _asset_map(assets)

    sections = "".join(
        _render_section(
            section,
            theme=theme,
            asset_urls=asset_urls,
        )
        for section in sorted(design.sections, key=lambda item: item.order)
    )

    mjml = (
        '<mjml>'
        '<mj-head>'
        f'<mj-title>{_safe_text(design.subject)}</mj-title>'
        f'<mj-preview>{_safe_text(design.preheader)}</mj-preview>'
        '<mj-attributes>'
        f'<mj-all font-family="{_safe_attr(theme["body_font"])}" />'
        '</mj-attributes>'
        '</mj-head>'
        f'<mj-body background-color="{_safe_attr(theme["background_color"])}" '
        f'width="{_safe_attr(theme["content_width"])}">'
        f'{sections}'
        '</mj-body>'
        '</mjml>'
    )

    return {
        "mjml": mjml,
        "resolved_theme": {
            key: value
            for key, value in theme.items()
            if key != "color_roles"
        },
        "rendered_sections": len(design.sections),
        "available_asset_ids": sorted(asset_urls.keys()),
    }
