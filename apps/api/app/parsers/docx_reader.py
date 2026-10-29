"""EB-204 — Đọc .docx giữ tín hiệu đáp án.

Lý do tự viết thay vì dùng mammoth: mammoth KHÔNG đọc w:color (màu chữ) —
đã kiểm chứng thực tế 2026-10-29, đáp án tô đỏ trong file Word bị mất hoàn toàn.
Bộ đọc này đi thẳng vào word/document.xml và giữ: màu chữ (w:color),
highlight (w:highlight / w:shd fill), in đậm (w:b), gạch chân (w:u).
"""
import io
import zipfile
import xml.etree.ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_HIGHLIGHT_HEX = {
    "yellow": "#ffff00", "green": "#00ff00", "cyan": "#00ffff", "magenta": "#ff00ff",
    "red": "#ff0000", "blue": "#0000ff", "lightgray": "#d3d3d3", "lightgrey": "#d3d3d3",
}


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _run_html(run) -> str:
    text = "".join(t.text or "" for t in run.iter(f"{W}t"))
    if not text:
        return ""
    rpr = run.find(f"{W}rPr")
    styles, wrap_b, wrap_u = [], False, False
    if rpr is not None:
        color = rpr.find(f"{W}color")
        if color is not None and color.get(f"{W}val") not in (None, "auto", "000000"):
            styles.append(f"color: #{color.get(f'{W}val').lower()}")
        hl = rpr.find(f"{W}highlight")
        if hl is not None and hl.get(f"{W}val") not in (None, "none"):
            styles.append(f"background-color: {_HIGHLIGHT_HEX.get(hl.get(f'{W}val'), '#ffff00')}")
        shd = rpr.find(f"{W}shd")
        if shd is not None and shd.get(f"{W}fill") not in (None, "auto"):
            styles.append(f"background-color: #{shd.get(f'{W}fill').lower()}")
        if rpr.find(f"{W}b") is not None:
            wrap_b = True
        u = rpr.find(f"{W}u")
        if u is not None and u.get(f"{W}val") != "none":
            wrap_u = True
    out = _esc(text)
    if styles:
        out = f'<span style="{"; ".join(styles)}">{out}</span>'
    if wrap_b:
        out = f"<b>{out}</b>"
    if wrap_u:
        out = f"<u>{out}</u>"
    return out


def docx_to_html(file_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    body = root.find(f"{W}body")
    paras = []
    for p in body.iter(f"{W}p"):
        runs = "".join(_run_html(r) for r in p.findall(f"{W}r"))
        if runs.strip():
            paras.append(f"<p>{runs}</p>")
        # body.iter cũng duyệt cả <w:p> nằm trong bảng (mỗi đoạn đúng 1 lần, giữ thứ tự)
    if not paras:
        raise ValueError("docx không có nội dung văn bản")
    return "\n".join(paras)
