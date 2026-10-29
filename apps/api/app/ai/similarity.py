"""EB-306 — Trùng NGỮ NGHĨA gần đúng: câu diễn đạt khác (hash khác) nhưng cùng nội dung.

Phương pháp không cần API ngoài: độ tương tự cosine trên tập từ của (thân câu + các phương án),
kèm kiểm tra tập phương án gần như trùng nhau. Khi có embedding thật (cột question_items.embedding,
pgvector) sẽ thay hàm này bằng truy vấn vector — giao diện giữ nguyên.
"""
import re

from sqlalchemy.orm import Session

from app.models import Option, QuestionItem

NEAR_DUP_THRESHOLD = 0.85

_STOP = set("the a an of to in on for with is are was were be been being it its this that "
            "which who whom what when where why how as at by from or and but not do does did".split())


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    return {w for w in words if w not in _STOP and len(w) > 1}


def similarity(stem_a: str, opts_a: list[str], stem_b: str, opts_b: list[str]) -> float:
    ta = _tokens(stem_a) | set().union(*[_tokens(o) for o in opts_a]) if opts_a else _tokens(stem_a)
    tb = _tokens(stem_b) | set().union(*[_tokens(o) for o in opts_b]) if opts_b else _tokens(stem_b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / (len(ta) * len(tb)) ** 0.5


def find_near_duplicates(db: Session, workspace_id, stem: str, options: list[str],
                         exclude_hash: str | None = None, limit: int = 3) -> list[dict]:
    """Tìm trong kho các câu tương tự >= ngưỡng với một câu ứng viên (chưa có trong kho)."""
    bank = (db.query(QuestionItem)
            .filter(QuestionItem.workspace_id == workspace_id).all())
    hits = []
    for q in bank:
        if exclude_hash and q.dedup_hash == exclude_hash:
            continue
        opts = [o.content_text for o in
                db.query(Option).filter_by(question_id=q.id).order_by(Option.position).all()]
        sim = similarity(stem, options, q.stem_text, opts)
        if sim >= NEAR_DUP_THRESHOLD:
            hits.append({"question_id": str(q.id), "similarity": round(sim, 3),
                         "stem_text": q.stem_text, "status": q.status.value})
    hits.sort(key=lambda h: -h["similarity"])
    return hits[:limit]
