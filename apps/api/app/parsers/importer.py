"""EB-201→205 — Dịch vụ nhập đề: sanitize -> parse -> lưu DB + ImportJob stats.

Dùng chung 1 đường duy nhất cho cả paste HTML (EB-202) và upload docx (EB-204,
file .docx được docx_reader chuyển thành HTML trước khi vào đây) để kết quả không lệch nhau.

Xử lý trùng lặp kiểu Windows Explorer (yêu cầu của Ha, 2026-10-29): nếu tỉ lệ câu trùng
với kho >= OVERLAP_ALERT_THRESHOLD (40%), KHÔNG nạp ngay — trả về bản trích lục so sánh
từng câu trùng (bản mới vs bản đang có) để giáo viên quyết định: ghi đè tất cả /
bỏ qua tất cả (chỉ nạp phần mới) / chọn riêng từng câu. Dưới ngưỡng thì nạp thẳng,
câu trùng bỏ qua như cũ.
"""
from sqlalchemy.orm import Session

from app.models import (
    AnswerSource, ImportJob, Option, PassageGroup, QuestionItem, QuestionStatus, SourceExam,
)
from app.parsers.docx_reader import docx_to_html  # noqa: F401  (re-export cho router/test)
from app.parsers.dedup import dedup_hash
from app.parsers.parser import parse_exam_html
from app.parsers.sanitize import sanitize_html

OVERLAP_ALERT_THRESHOLD = 0.40


def _existing_snapshot(db: Session, item: QuestionItem) -> dict:
    options = (db.query(Option).filter_by(question_id=item.id)
               .order_by(Option.position).all())
    correct_label = None
    if item.correct_option_id:
        for o in options:
            if o.id == item.correct_option_id:
                correct_label = o.label
    exam_title = None
    if item.source_exam_id:
        ex = db.get(SourceExam, item.source_exam_id)
        exam_title = ex.title if ex else None
    return {
        "question_id": str(item.id), "stem_text": item.stem_text,
        "options": [{"label": o.label, "content_text": o.content_text} for o in options],
        "correct_label": correct_label,
        "answer_source": item.answer_source.value if hasattr(item.answer_source, "value") else item.answer_source,
        "status": item.status.value if hasattr(item.status, "value") else item.status,
        "source_exam_title": exam_title,
    }


def _analyze(db: Session, exam: SourceExam, parsed: dict) -> dict:
    """Phân loại từng câu parse được: mới / trùng với kho / trùng trong chính file."""
    existing_by_hash = {
        q.dedup_hash: q for q in
        db.query(QuestionItem).filter(QuestionItem.workspace_id == exam.workspace_id).all()
    }
    entries, seen_in_file = [], set()
    total_valid = duplicates = 0
    for q in parsed["questions"]:
        if not q["options"]:
            entries.append({"q": q, "hash": None, "existing": None, "failed": True})
            continue
        total_valid += 1
        h = dedup_hash(q["stem"], [o["text"] for o in q["options"]])
        existing = existing_by_hash.get(h)
        if existing is None and h in seen_in_file:
            existing = "self"  # trùng với chính câu trước trong cùng file nạp
        if existing is not None:
            duplicates += 1
        else:
            seen_in_file.add(h)
        entries.append({"q": q, "hash": h, "existing": existing, "failed": False})
    ratio = (duplicates / total_valid) if total_valid else 0.0
    return {"entries": entries, "total_valid": total_valid,
            "duplicates": duplicates, "overlap_ratio": ratio}


def _create_question(db, exam, q, h, passage_id, created_by) -> QuestionItem:
    det = q["detected_answer"]
    item = QuestionItem(
        workspace_id=exam.workspace_id, source_exam_id=exam.id, passage_id=passage_id,
        question_type=q["question_type"], order_in_source=q["number"],
        stem_html=q.get("stem_html") or q["stem"], stem_text=q["stem"],
        status=QuestionStatus.pending_review if det else QuestionStatus.needs_answer,
        answer_source=AnswerSource(det["source"]) if det else AnswerSource.unknown,
        answer_confidence=det["confidence"] if det else None,
        dedup_hash=h, created_by=created_by,
    )
    db.add(item)
    db.flush()
    correct_id = None
    for i, o in enumerate(q["options"]):
        opt = Option(question_id=item.id, label=o["label"],
                     content_html=o.get("html") or o["text"], content_text=o["text"], position=i)
        db.add(opt)
        db.flush()
        if det and o["label"] == det["label"]:
            correct_id = opt.id
    item.correct_option_id = correct_id
    return item


def _overwrite_question(db, existing: QuestionItem, q, passage_id) -> None:
    """Ghi đè câu đã có bằng bản mới (cùng dedup_hash nên stem/options text giống hệt;
    cái mới hơn thường là đáp án/định dạng/passage đầy đủ hơn). Câu đã duyệt bị đưa về
    chờ duyệt lại vì nội dung nền đã thay đổi."""
    det = q["detected_answer"]
    old_correct_text = None
    if existing.correct_option_id:
        oc = db.get(Option, existing.correct_option_id)
        old_correct_text = oc.content_text if oc else None
    db.query(Option).filter_by(question_id=existing.id).delete()
    existing.stem_html = q.get("stem_html") or q["stem"]
    existing.stem_text = q["stem"]
    existing.question_type = q["question_type"]
    if passage_id:
        existing.passage_id = passage_id
    correct_id = None
    for i, o in enumerate(q["options"]):
        opt = Option(question_id=existing.id, label=o["label"],
                     content_html=o.get("html") or o["text"], content_text=o["text"], position=i)
        db.add(opt)
        db.flush()
        if det and o["label"] == det["label"]:
            correct_id = opt.id
        elif not det and old_correct_text and o["text"] == old_correct_text:
            correct_id = opt.id  # bản mới không có dấu đáp án -> giữ đáp án cũ theo nội dung
    existing.correct_option_id = correct_id
    if det:
        existing.answer_source = AnswerSource(det["source"])
        existing.answer_confidence = det["confidence"]
    elif not correct_id:
        existing.answer_source = AnswerSource.unknown
        existing.answer_confidence = None
    existing.status = QuestionStatus.pending_review if correct_id else QuestionStatus.needs_answer
    existing.reviewed_by = None
    existing.reviewed_at = None
    db.flush()


def run_import(db: Session, exam: SourceExam, html: str, created_by,
               on_conflict: str = "ask", decisions: dict | None = None) -> dict:
    """Trả {"status": "done", job_id, stats} hoặc {"status": "conflict", ...trích lục so sánh...}.

    on_conflict: "ask" (mặc định, dừng hỏi khi trùng >= ngưỡng) | "keep_old" | "overwrite" | "decide"
    decisions: {dedup_hash: "overwrite"|"keep"} — chỉ dùng với on_conflict="decide",
    câu trùng không có quyết định riêng thì mặc định giữ bản cũ.
    """
    clean_html = sanitize_html(html)
    parsed = parse_exam_html(clean_html)
    analysis = _analyze(db, exam, parsed)

    if (on_conflict == "ask" and analysis["duplicates"] > 0
            and analysis["overlap_ratio"] >= OVERLAP_ALERT_THRESHOLD):
        dups = []
        for e in analysis["entries"]:
            if e["existing"] is None or e["existing"] == "self" or e["failed"]:
                continue
            q = e["q"]
            dups.append({
                "dedup_hash": e["hash"], "number": q["number"],
                "new": {"stem_text": q["stem"],
                        "options": [{"label": o["label"], "content_text": o["text"]} for o in q["options"]],
                        "detected_answer": q["detected_answer"]},
                "existing": _existing_snapshot(db, e["existing"]),
            })
        return {"status": "conflict", "overlap_ratio": round(analysis["overlap_ratio"], 3),
                "threshold": OVERLAP_ALERT_THRESHOLD, "total": analysis["total_valid"],
                "duplicate_count": analysis["duplicates"],
                "new_count": analysis["total_valid"] - analysis["duplicates"],
                "duplicates": dups}

    # --- Áp dụng ---
    exam.raw_html = clean_html  # EB-201: giữ bản gốc đã làm sạch để đối chiếu/debug parser
    job = ImportJob(source_exam_id=exam.id, status="parsing", stats={}, error_log=[])
    db.add(job)
    db.flush()

    passage_by_temp: dict[str, PassageGroup] = {}
    for p in parsed["passages"]:
        pg = PassageGroup(
            source_exam_id=exam.id, workspace_id=exam.workspace_id,
            passage_type=p["passage_type"], content_html=p.get("content_html") or p["content_text"],
            content_text=p["content_text"],
        )
        db.add(pg)
        db.flush()
        passage_by_temp[p["temp_id"]] = pg

    stats = {"total": 0, "with_answer": 0, "needs_answer": 0,
             "duplicates": 0, "overwritten": 0, "failed": 0, "near_duplicates": 0}
    errors = []
    near_dups: list[dict] = []
    for e in analysis["entries"]:
        q = e["q"]
        stats["total"] += 1
        if e["failed"]:
            stats["failed"] += 1
            errors.append({"question": q["number"], "issue": "no_options_parsed"})
            continue
        passage_id = (passage_by_temp[q["passage_temp_id"]].id if q.get("passage_temp_id") else None)
        if e["existing"] is None:
            item = _create_question(db, exam, q, e["hash"], passage_id, created_by)
            # EB-306: cảnh báo trùng ngữ nghĩa với câu KHÁC hash đã có trong kho (không chặn nạp)
            from app.ai.similarity import find_near_duplicates
            for hit in find_near_duplicates(db, exam.workspace_id, q["stem"],
                                            [o["text"] for o in q["options"]],
                                            exclude_hash=e["hash"]):
                near_dups.append({"number": q["number"], "stem_text": q["stem"], **hit})
            if item.correct_option_id:
                stats["with_answer"] += 1
            else:
                stats["needs_answer"] += 1
            continue
        # Câu trùng: quyết định theo chế độ
        if e["existing"] == "self":
            stats["duplicates"] += 1
            continue
        action = on_conflict
        if on_conflict == "decide":
            action = "overwrite" if (decisions or {}).get(e["hash"]) == "overwrite" else "keep_old"
        if action == "overwrite":
            _overwrite_question(db, e["existing"], q, passage_id)
            stats["overwritten"] += 1
            if e["existing"].correct_option_id:
                stats["with_answer"] += 1
            else:
                stats["needs_answer"] += 1
        else:  # keep_old và ask dưới ngưỡng đều giữ bản cũ
            stats["duplicates"] += 1

    stats["near_duplicates"] = len(near_dups)
    job.stats = stats
    job.error_log = errors
    job.status = "done"
    db.commit()
    db.refresh(job)
    return {"status": "done", "job_id": str(job.id), "stats": stats, "error_log": errors,
            "near_duplicates": near_dups}


def import_html(db: Session, exam: SourceExam, html: str, created_by) -> ImportJob:
    """Wrapper tương thích ngược (test/caller cũ): nạp thẳng, trùng thì giữ bản cũ."""
    import uuid as _uuid
    result = run_import(db, exam, html, created_by, on_conflict="keep_old")
    return db.get(ImportJob, _uuid.UUID(result["job_id"]))
