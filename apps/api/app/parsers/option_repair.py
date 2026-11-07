"""Sửa dữ liệu cũ: phương án bị DÍNH nhãn kế tiếp vào cuối text.

Dữ liệu đã nạp trước khi parser biết xử lý nhãn dính (vd "ideal spacious modernB.
modern spacious ideal" trong option A, nhãn B không tồn tại) khiến GV không chọn
được đáp án B/D khi duyệt (PATCH correct_label=B -> 422). Hàm này tách option dính
thành 2 option đúng nhãn, chạy lười (lazy) khi GV mở màn duyệt / kho câu hỏi.

Cách xác định: đi theo thứ tự position, nhãn phải chạy liên tục từ A. Nhãn THIẾU
đầu tiên (vd có A rồi nhảy sang C -> thiếu B) chỉ có thể đang dính trong text của
option đứng ngay trước nó — tách tại "B. " trong text đó. An toàn: chỉ tách khi
nhãn tìm thấy đúng bằng nhãn đang thiếu và phần tách nằm sau ký tự đầu; nhãn lộn
xộn/trùng (không suy đoán được) thì dừng. Option cũ giữ phần đầu (cả content_text
và content_html thành text sạch dạng plain — định dạng nhấn mạnh trong phần bị
dính vốn đã không tách tin cậy được), option mới mang nhãn thiếu + phần đuôi.
"""
import re

from sqlalchemy.orm import Session

from app.models import Option, QuestionItem

_GLUED_LABEL = re.compile(r"([A-D])\.\s+")


def _next(label: str) -> str:
    return chr(ord(label) + 1)


def repair_glued_options(db: Session, question: QuestionItem) -> bool:
    """Tách các option dính của 1 câu. Trả True nếu có thay đổi (chưa commit —
    nơi gọi tự commit)."""
    changed = False
    while True:
        options = (db.query(Option).filter_by(question_id=question.id)
                   .order_by(Option.position).all())
        if len(options) >= 4:
            break
        # Tìm nhãn thiếu đầu tiên trong dãy chạy từ A + option đứng ngay trước nó
        expected, prev, missing = "A", None, None
        for opt in options:
            if opt.label == expected:
                expected, prev = _next(expected), opt
                continue
            if opt.label > expected:
                missing = expected  # nhãn nhảy cóc -> nhãn thiếu nằm trong text của prev
            break  # nhãn trùng/lùi (opt.label < expected): không suy đoán
        else:
            missing = expected  # hết option mà dãy chưa đủ: nhãn kế tiếp có thể dính ở option cuối
        if missing is None or missing > "D" or prev is None:
            break
        text = prev.content_text or ""
        m = None
        for cand in _GLUED_LABEL.finditer(text):
            if cand.group(1) == missing and cand.start() > 0:
                m = cand
                break
        if m is None:
            break
        head = text[: m.start()].rstrip()
        tail = text[m.end():].strip()
        if not head or not tail:
            break
        prev.content_text = head
        prev.content_html = head
        for other in options:
            if other.position > prev.position:
                other.position += 1
        db.add(Option(question_id=question.id, label=missing,
                      content_text=tail, content_html=tail,
                      position=prev.position + 1))
        db.flush()
        changed = True
    return changed
