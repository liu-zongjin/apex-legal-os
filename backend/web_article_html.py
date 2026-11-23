"""Build a self-contained article fragment from an external article DOM."""

import re
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup, Comment, Tag

from .article_structure import classify_article_block

HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
CONTAINERS = {"main", "article", "div", "section", "header", "nav", "aside", "font"}
BLOCKS = HEADINGS | {
    "div", "p", "ul", "ol", "li", "blockquote", "pre", "figure", "figcaption",
    "hr", "table", "caption", "colgroup", "col", "thead", "tbody", "tfoot", "tr", "th", "td",
    "dl", "dt", "dd",
}
REMOVE = {
    "script", "style", "iframe", "object", "embed", "template", "form", "input",
    "button", "select", "textarea", "svg", "math", "canvas", "audio", "video",
    "noscript", "link", "meta", "base",
}
INLINE = {"a", "span", "strong", "b", "em", "i", "u", "s", "del", "mark", "br", "img", "code", "sub", "sup", "small"}
LAYOUT = {
    "text-align": "left right center justify start end",
    "display": "block inline inline-block flex inline-flex",
    "flex-direction": "row column",
    "flex-wrap": "wrap nowrap",
    "align-items": "start end flex-start flex-end center baseline stretch",
    "justify-content": "start end flex-start flex-end center space-between space-around space-evenly",
    "vertical-align": "baseline top middle bottom sub super text-top text-bottom",
    "white-space": "normal pre pre-wrap pre-line break-spaces",
    "list-style-type": "none disc circle square decimal decimal-leading-zero lower-alpha upper-alpha lower-roman upper-roman cjk-ideographic simp-chinese-informal",
    "list-style-position": "inside outside",
    "border-collapse": "collapse separate",
    "font-style": "normal italic oblique",
    "text-decoration": "none underline line-through overline",
}
COLOR = r"(?:#[0-9a-f]{3,8}|[a-z]{1,24}|(?:rgba?|hsla?)\([\d\s.,%/+\-]+\))"
LENGTH = re.compile(r"(\d+(?:\.\d+)?|\.\d+)(px|rem|em|%|ch|pt)?")
SIDES = {"", "-top", "-right", "-bottom", "-left"}
GAPS = {prefix + side for prefix in ("margin", "padding") for side in SIDES}
BORDERS = {"border" + side for side in SIDES}
BORDER_STYLE = r"(?:none|solid|dashed|dotted|double)"
TOC_LABEL = re.compile(r"^(?:目录|目次|contents|table of contents)\s*[:：]?$", re.I)
TOC_NUMBER = re.compile(r"^(?:[一二三四五六七八九十]+\s*[、.．]?|\d{1,3}\s*[.．、)）]|[（(][一二三四五六七八九十\d]+[）)])\s*")
DECORATION = re.compile(r"^[·•.・…\-—\s]+$")
ANCHOR_HINT = re.compile(r"(?:^|[\s_-])(?:toc|table-of-contents|article-contents)(?:$|[\s_-])", re.I)
RASTER_DATA = re.compile(r"data:image/(?:png|jpe?g|gif|webp);base64,[a-z0-9+/=]+", re.I)


def _length(value, limit=192, relative_limit=12, percent_limit=100, unitless_limit=0):
    match = LENGTH.fullmatch(value)
    if not match:
        return False
    magnitude, unit = match.groups()
    bounds = {"%": percent_limit, "px": limit, "pt": limit * .75, None: unitless_limit}
    return float(magnitude) <= bounds.get(unit, relative_limit)


def _lengths(value, count=1, **limits):
    parts = value.split()
    return 1 <= len(parts) <= count and all(_length(part, **limits) for part in parts)


def _safe_css_value(name, value):
    # Values are parsed from a deliberately small grammar. No URLs, variables,
    # escapes, comments, positioning, negative margins or executable CSS.
    if name in LAYOUT:
        return value in LAYOUT[name].split()
    if name in {"color", "background", "background-color"}:
        return bool(re.fullmatch(COLOR, value))
    if name in GAPS:
        if name.startswith("margin") and value == "auto":
            return True
        return _lengths(value, 4 if name in {"margin", "padding"} else 1, limit=96, relative_limit=6, percent_limit=25)
    if name in {"font-size", "line-height", "letter-spacing", "text-indent", "border-radius", "gap", "column-gap", "row-gap"}:
        if name in {"line-height", "letter-spacing"} and value == "normal":
            return True
        if name == "font-size":
            return _lengths(value, limit=72, relative_limit=4, percent_limit=350)
        if name == "line-height":
            return _lengths(value, limit=120, relative_limit=4, percent_limit=400, unitless_limit=4)
        return _lengths(value, 4 if name == "border-radius" else 1, limit=96, relative_limit=6, percent_limit=50)
    if name in {"width", "max-width", "height", "max-height"}:
        return value == "auto" or _lengths(value, limit=2400, relative_limit=120)
    if name in BORDERS:
        match = re.fullmatch(rf"(\S+)\s+({BORDER_STYLE})(?:\s+{COLOR})?", value)
        return value == "none" or bool(match and _length(match[1], limit=12, relative_limit=1, percent_limit=0))
    if name in {side + "-color" for side in BORDERS}:
        return bool(re.fullmatch(COLOR, value))
    if name in {side + "-width" for side in BORDERS}:
        return _lengths(value, 4 if name == "border-width" else 1, limit=12, relative_limit=1, percent_limit=0)
    if name in {side + "-style" for side in BORDERS}:
        return bool(re.fullmatch(rf"{BORDER_STYLE}(?:\s+{BORDER_STYLE}){{0,3}}", value))
    if name == "font-weight":
        return bool(re.fullmatch(r"normal|bold|[1-9]00", value))
    if name == "flex-shrink":
        return value in {"0", "1"}
    return False


def _style(raw):
    declarations = {}
    for declaration in str(raw or "").split(";"):
        name, separator, value = declaration.partition(":")
        name, value = name.strip().lower(), value.strip().lower()
        if separator and len(value) <= 128 and _safe_css_value(name, value):
            # Keep shorthand/longhand cascade order even when a name repeats.
            declarations.pop(name, None)
            declarations[name] = value
    return declarations


def _url(value, page_url, image=False):
    value = str(value or "").strip()
    if not value or re.search(r"[\x00-\x20\x7f\\]", value):
        return ""
    if image and RASTER_DATA.fullmatch(value):
        return value
    if value.startswith("#"):
        return value if not image else ""
    try:
        absolute = urljoin(page_url, value)
        parsed = urlsplit(absolute)
        if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password:
            return absolute
        if not image and parsed.scheme == "mailto" and parsed.path:
            return absolute
    except ValueError:
        pass
    return ""


def _image_source(node, page_url, style):
    src = node.get("src", "")
    lazy = next((node[key] for key in ("data-src", "data-backsrc", "data-original", "data-lazy-src")
                 if node.get(key)), "")
    classes = set(node.get("class", []))
    width = style.get("width", "")
    if not width:
        width = _style(node.get("data-original-style")).get("width", "")
    decorative = (node.get("data-type") == "gif" or classes & {"__bg_gif", "wx_img_placeholder_mini"})
    if decorative and width.endswith("px") and _length(width, limit=96):
        return ""
    if len(src) > 512 and RASTER_DATA.fullmatch(src):
        return src
    return _url(lazy, page_url, image=True) or _url(src, page_url, image=True)


def _contains_blocks(node):
    return any(isinstance(child, Tag) and child.name in BLOCKS for child in node.children)


def _group_inline_runs(container, fragment):
    """Turn runs of loose inline nodes into one paragraph per source block."""
    paragraph = None
    for child in list(container.children):
        if isinstance(child, Tag) and child.name in BLOCKS:
            paragraph = None
            continue
        if paragraph is None:
            paragraph = fragment.new_tag("p")
            child.insert_before(paragraph)
        paragraph.append(child.extract())
    for paragraph in container.find_all("p", recursive=False):
        if not paragraph.get_text(strip=True) and not paragraph.find(["br", "img"]) and not paragraph.attrs:
            paragraph.decompose()


def _block_text(node):
    return re.sub(r"\s+", " ", node.get_text()).strip()


def _toc_key(text):
    return re.sub(r"\s+", "", TOC_NUMBER.sub("", text)).rstrip(":：")


def _toc_regions(root):
    blocks = [node for node in root.find_all(["p", "li", *HEADINGS])
              if not node.find(["p", "li", *HEADINGS]) and not node.find_parent(["table", "blockquote"])]
    for wrapper in root.select(".body-web-toc"):
        for row in blocks:
            if wrapper in row.parents:
                row["class"] = ["body-web-toc-label" if TOC_LABEL.fullmatch(_block_text(row)) else "body-web-toc-entry"]
    for label_index, label in enumerate(blocks[:30]):
        if label.get("class") or not TOC_LABEL.fullmatch(_block_text(label)):
            continue
        entries = []
        keys = set()
        end = label_index + 1
        for end, row in enumerate(blocks[label_index + 1:label_index + 61], label_index + 1):
            text = _block_text(row)
            if not text:
                continue
            key = _toc_key(text)
            if not key or len(text) > 95 or DECORATION.fullmatch(text) or key in keys or re.search(r"[。；;]$", text):
                break
            entries.append(row)
            keys.add(key)
        if len(entries) < 2:
            continue
        # Require a real container, an initial sequence of numbered rows, or
        # matching section titles later in the article. Stop at the first repeat.
        wrapper = label.parent
        while wrapper is not root and not all(wrapper in row.parents for row in entries):
            wrapper = wrapper.parent
        separate = wrapper is not root and len([row for row in blocks if wrapper in row.parents]) == len(entries) + 1
        later = {_toc_key(_block_text(row)) for row in blocks[end:]}
        if not separate and len(keys & later) < 2:
            numbered = []
            for row in entries:
                if row.name != "li" and not TOC_NUMBER.match(_block_text(row)) and not row.find("a", href=re.compile(r"^#")):
                    break
                numbered.append(row)
            entries = numbered
        if len(entries) < 2:
            continue
        label["class"] = ["body-web-toc-label"]
        for row in entries:
            row["class"] = [*row.get("class", []), "body-web-toc-entry"]
        if separate:
            wrapper["class"] = [*wrapper.get("class", []), "body-web-toc"]
        break


def _heading_role(node):
    text = _block_text(node)
    if not text or len(text) > 90 or node.find(["img", "br"]) or node.find_parent(["blockquote", "li", "table", "figure"]):
        return ""
    if {"body-web-toc-label", "body-web-toc-entry"} & set(node.get("class", [])):
        return ""
    style = _style(node.get("style"))
    parent = node.parent
    while parent.name == "div" and "body-web-import" not in parent.get("class", []) and _block_text(parent) == text:
        style = {**_style(parent.get("style")), **style}
        parent = parent.parent
    spans = node.find_all(["span", "strong", "b"])
    span_styles = [_style(span.get("style")) for span in spans]
    has_border = "border-left" in style or {"border-left-style", "border-left-width"} <= style.keys()
    banner = any(key in style for key in ("background", "background-color"))
    badge = bool(spans and re.fullmatch(r"[一二三四五六七八九十]+|\d{1,2}", _block_text(spans[0]))
                 and any(key in span_styles[0] for key in ("background", "background-color")))
    bold = (style.get("font-weight") in {"bold", "600", "700", "800", "900"}
            or any(_block_text(span) == text and (
                span.name in {"strong", "b"} or span_style.get("font-weight") in {"bold", "600", "700", "800", "900"}
            ) for span, span_style in zip(spans, span_styles)))
    visual = has_border or banner or badge
    role = classify_article_block(text, explicit_heading=visual or bold, bold=bold)
    if visual and role in {"body-heading", "body-heading-secondary"}:
        return "h3" if has_border and not (banner or badge) else "h2"
    if role == "body-heading" and (bold or TOC_NUMBER.match(text) or text.startswith("第")):
        return "h2"
    if role in {"body-heading-secondary", "body-label-heading"} and (bold or text.startswith("第") or role == "body-label-heading"):
        return "h3"
    return ""


def extract_web_article_html(element, page_url):
    """Preserve source structure and safe inline presentation before storage."""
    import copy

    source = copy.copy(element)
    fragment = BeautifulSoup("", "html.parser")
    root = fragment.new_tag("div", attrs={"class": "body-web-import"})
    # The source page may apply display:none to the entire article until its
    # scripts run. The selected article container is always included.
    root_style = _style(source.get("style"))
    for property in ("display", "width", "height", "max-width", "max-height"):
        root_style.pop(property, None)
    if root_style:
        root["style"] = ";".join(f"{key}:{value}" for key, value in root_style.items())
    if source.name in {"[document]", "html"} and source.body:
        source = source.body
    for child in list(source.children):
        root.append(child.extract())

    anchors = {}
    has_palette = any(key in root_style for key in ("color", "background", "background-color"))
    for node in list(root.find_all(True)):
        if node.attrs is None:
            continue  # An ancestor was discarded.
        raw_style = node.get("style", "")
        if node.name in REMOVE or node.has_attr("hidden") or re.search(
                r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:!important\s*)?(?:;|$)",
                raw_style, re.I):
            node.decompose()
            continue

        tag = node.name
        if tag not in BLOCKS | INLINE | CONTAINERS:
            node.unwrap()
            continue
        toc_hint = bool(TOC_LABEL.fullmatch(node.get("aria-label", "")) or ANCHOR_HINT.search(
            " ".join([node.get("id", ""), *node.get("class", [])])))
        if tag == "nav" and not toc_hint:
            node.decompose()
            continue
        if tag == "aside" and not toc_hint:
            node.decompose()
            continue
        attrs = {}
        if toc_hint and tag in CONTAINERS:
            attrs["class"] = ["body-web-toc"]
        if tag in {"ol", "ul"}:
            attrs["class"] = ["body-web-native-list"]
        style = _style(raw_style)
        if tag in CONTAINERS:
            node.name = "span" if tag == "font" else "div"
            if tag == "font" and _safe_css_value("color", node.get("color", "").lower()):
                style.setdefault("color", node["color"].lower())
        if style:
            has_palette |= any(key in style for key in ("color", "background", "background-color"))
            attrs["style"] = ";".join(f"{key}:{value}" for key, value in style.items())
        ident = node.get("id") or (node.get("name") if tag == "a" else "")
        if ident and ident not in anchors:
            attrs["data-web-anchor"] = anchors[ident] = f"web-source-{len(anchors) + 1}"
        if tag == "img":
            src = _image_source(node, page_url, style)
            if not src:
                node.decompose()
                continue
            attrs.update(src=src, alt=node.get("alt", "")[:300])
        if tag == "a":
            href = _url(node.get("href"), page_url)
            if href:
                attrs["href"] = href
                if not href.startswith("#"):
                    attrs.update(target="_blank", rel="noopener noreferrer")
        if tag in {"a", "img"} and node.get("title"):
            attrs["title"] = node["title"][:300]
        numeric_attrs = {"ol": ("start",), "li": ("value",), "th": ("colspan", "rowspan"),
                         "td": ("colspan", "rowspan"), "img": ("width", "height"),
                         "col": ("span",), "colgroup": ("span",)}
        for key in numeric_attrs.get(tag, ()):
            value = str(node.get(key, ""))
            pattern = r"-?\d{1,4}" if key in {"start", "value"} else r"[1-9]\d{0,3}"
            if re.fullmatch(pattern, value):
                attrs[key] = value
        if tag == "ol" and node.has_attr("reversed"):
            attrs["reversed"] = ""
        if tag == "ol" and node.get("type") in {"1", "A", "a", "I", "i"}:
            attrs["type"] = node["type"]
        node.attrs = attrs

    for comment in root.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    for node in reversed(root.find_all("div")):
        if not _contains_blocks(node) and "body-web-toc" not in node.get("class", []):
            node.name = "p"
        else:
            _group_inline_runs(node, fragment)
            node["class"] = [*node.get("class", []), "body-web-block"]
    if has_palette:
        root["class"].append("body-web-palette")
    _group_inline_runs(root, fragment)
    for link in root.select("a[href^='#']"):
        anchor = anchors.get(unquote(link["href"][1:]))
        if anchor:
            link["href"] = "#" + anchor
        else:
            del link["href"]
    _toc_regions(root)
    for node in root.find_all("p"):
        role = _heading_role(node)
        if role:
            node.name = role
    for table in root.find_all("table"):
        table.wrap(fragment.new_tag("div", attrs={"class": "body-web-block body-web-table"}))
    return str(root) if root.get_text(strip=True) or root.find("img") else ""
