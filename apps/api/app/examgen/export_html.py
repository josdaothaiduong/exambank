"""EB-405 — Bản in HTML của một mã đề: cùng nguồn snapshot với bản Word nên nội dung
khớp tuyệt đối; giáo viên dùng nút In của trình duyệt để lưu PDF."""
import html as html_lib

from app.examgen.export_docx import _version_items  # dùng chung cách lấy snapshot
from app.models import Exam, ExamVersion
from sqlalchemy.orm import Session

CSS = """
body { font-family: 'Times New Roman', serif; font-size: 14pt; max-width: 820px; margin: 24px auto; padding: 0 16px; }
h1 { font-size: 15pt; text-align: center; margin: 4px 0; }
.meta { text-align: center; font-weight: bold; margin-bottom: 6px; }
.passage { font-style: italic; margin: 10px 0 10px 18px; }
.q { margin-top: 12px; }
.opt { margin-left: 24px; }
.correct { font-weight: bold; text-decoration: underline; }
.key { border-collapse: collapse; margin-top: 12px; }
.key td { border: 1px solid #444; padding: 2px 8px; text-align: center; }
@media print { .noprint { display: none; } body { margin: 0 auto; } }
"""


def build_print_html(db: Session, exam: Exam, version: ExamVersion, teacher: bool) -> str:
    items = _version_items(db, version)
    parts = [f"<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
             f"<title>{html_lib.escape(exam.title)} — Mã {version.code}</title>"
             f"<style>{CSS}</style></head><body>"]
    parts.append("<h1>ĐỀ KIỂM TRA — MÔN: TIẾNG ANH</h1>")
    parts.append(f"<div class='meta'>{html_lib.escape(exam.title)} · Mã đề: {version.code}"
                 f" · Thời gian: {exam.duration_minutes or ''} phút</div>")
    if teacher:
        parts.append("<div class='meta'>(BẢN GIÁO VIÊN — đáp án đúng được in đậm, gạch chân)</div>")
    parts.append("<div>Họ và tên học sinh: ............................................................ Lớp: .................</div>")
    printed: set[str] = set()
    for it in items:
        if it.get("passage_id") and it["passage_id"] not in printed:
            printed.add(it["passage_id"])
            passage = it.get("passage") or {}
            if passage.get("title"):
                parts.append(f"<div class='passage'>{passage['title']}</div>")
            parts.append(f"<div class='passage'>{passage.get('content_html') or ''}</div>")
        parts.append(f"<div class='q'><b>Câu {it['position']}:</b> {it['stem_html']}</div>")
        for o in it["options"]:
            cls = " class='correct'" if teacher and o["label"] == it["correct_label"] else ""
            parts.append(f"<div class='opt'{cls}>{o['label']}. {o['html']}</div>")
        if teacher and it.get("explanation_html"):
            parts.append(f"<div class='opt'><i>Giải thích: {it['explanation_html']}</i></div>")
    if teacher:
        parts.append(f"<h3>BẢNG ĐÁP ÁN — Mã đề {version.code}</h3><table class='key'>")
        for start in range(0, len(items), 10):
            chunk = items[start:start + 10]
            parts.append("<tr>" + "".join(f"<td>{it['position']}</td>" for it in chunk) + "</tr>")
            parts.append("<tr>" + "".join(f"<td><b>{it['correct_label'] or ''}</b></td>" for it in chunk) + "</tr>")
        parts.append("</table>")
    parts.append("<p class='noprint'><button onclick='window.print()'>🖨 In / Lưu PDF</button></p>")
    parts.append("</body></html>")
    return "".join(parts)
