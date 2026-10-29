"""EB-201 — Sanitize HTML phía server.

Chỉ giữ những gì mang ý nghĩa đáp án: color, background-color, in đậm, gạch chân.
Xóa script/style/img/link và mọi thuộc tính khác (class, id, href...) để chống XSS
và để parser ở bước sau đọc tín hiệu đáp án một cách nhất quán.
Hỗ trợ cả <font color="red"> kiểu Word cũ.
"""
from bs4 import BeautifulSoup

_DROP_TAGS = ["script", "style", "img", "link", "meta", "iframe", "object", "embed", "form", "input", "button"]
_KEEP_STYLE_KEYS = {"color", "background-color", "font-weight", "text-decoration"}


def _parse_style(style: str) -> dict:
    out = {}
    for part in (style or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            k, v = k.strip().lower(), v.strip()
            if k in _KEEP_STYLE_KEYS and v:
                out[k] = v
    return out


def sanitize_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag_name in _DROP_TAGS:
        for t in soup.find_all(tag_name):
            t.decompose()
    for el in soup.find_all(True):
        # <font color="red"> -> style color
        font_color = el.get("color") if el.name == "font" else None
        styles = _parse_style(el.get("style", ""))
        if font_color:
            styles["color"] = font_color
        # Xóa mọi thuộc tính, chỉ đặt lại style đã lọc
        el.attrs = {}
        if styles:
            el["style"] = "; ".join(f"{k}: {v}" for k, v in styles.items())
    body = soup.body or soup
    return "".join(str(c) for c in body.contents)
