"""EB-303 — Pipeline giải đề: provider -> self-check (xáo trộn phương án, giải độc lập)
-> lưu ai_solutions + cập nhật câu hỏi (answer_source=ai_solved, chờ giáo viên duyệt).

Nguyên tắc bất biến: AI chỉ ĐỀ XUẤT. Câu sau khi giải ở trạng thái pending_review,
chỉ vào kho khi giáo viên duyệt; confidence < 0.70 bị cổng duyệt chặn (xem routers/imports).
"""
import html as html_lib

from sqlalchemy.orm import Session

from app.ai.prompts import SYSTEM_PROMPT, build_selfcheck_prompt, build_user_prompt
from app.ai.provider import BaseProvider, ProviderError
from app.models import (
    AISolution, AnswerSource, Difficulty, Option, PassageGroup, QuestionItem, QuestionStatus,
)

CONFIDENCE_GATE = 0.70


def _options_of(db: Session, q: QuestionItem) -> list[Option]:
    return (db.query(Option).filter_by(question_id=q.id)
            .order_by(Option.position).all())


def solve_question(db: Session, q: QuestionItem, provider: BaseProvider) -> dict:
    options = _options_of(db, q)
    if len(options) < 2:
        return {"question_id": str(q.id), "status": "failed", "error": "Câu thiếu phương án"}
    passage_text = None
    if q.passage_id:
        p = db.get(PassageGroup, q.passage_id)
        passage_text = p.content_text if p else None
    opt_payload = [{"label": o.label, "text": o.content_text} for o in options]
    valid_labels = {o.label for o in options}

    q.status = QuestionStatus.ai_solving
    db.flush()
    try:
        first = provider.solve(
            system=SYSTEM_PROMPT,
            user=build_user_prompt(stem=q.stem_text, options=opt_payload,
                                   question_type=q.question_type, passage_text=passage_text),
            valid_labels=valid_labels)
        # Self-check: xáo trộn thứ tự (xoay vòng 1), nhãn đổi theo — đáp án phải trỏ về
        # cùng một NỘI DUNG thì mới đáng tin.
        rotated = opt_payload[1:] + opt_payload[:1]
        label_map = {}  # nhãn mới -> nhãn gốc (theo nội dung)
        shuffled_payload = []
        for new_label, orig in zip("ABCD", rotated):
            shuffled_payload.append({"label": new_label, "text": orig["text"]})
            label_map[new_label] = orig["label"]
        check = provider.solve(
            system=SYSTEM_PROMPT,
            user=build_selfcheck_prompt(stem=q.stem_text, options=shuffled_payload,
                                        question_type=q.question_type, passage_text=passage_text),
            valid_labels=valid_labels)
    except ProviderError as e:
        q.status = QuestionStatus.needs_answer
        db.flush()
        return {"question_id": str(q.id), "status": "failed", "error": str(e)}

    sol = first["solution"]
    check_label_orig = label_map[check["solution"]["answer_label"]]
    agree = check_label_orig == sol["answer_label"]
    if agree:
        confidence = min(0.99, (sol["confidence"] + check["solution"]["confidence"]) / 2 + 0.05)
    else:
        confidence = max(0.10, min(sol["confidence"], check["solution"]["confidence"]) - 0.25)

    suggested = next(o for o in options if o.label == sol["answer_label"])
    usage = {"input_tokens": first["usage"]["input_tokens"] + check["usage"]["input_tokens"],
             "output_tokens": first["usage"]["output_tokens"] + check["usage"]["output_tokens"]}
    cost = provider.cost_usd(first["usage"]) + provider.cost_usd(check["usage"])
    explanation = sol["explanation_vi"]
    if not agree:
        explanation += (" [Kiểm chứng chéo: lần giải thứ hai (đã xáo trộn phương án) cho đáp án khác"
                        " — độ tin cậy đã bị hạ, giáo viên cần kiểm tra kỹ.]")

    db.add(AISolution(
        question_id=q.id, model=provider.model, suggested_option_id=suggested.id,
        explanation_html=f"<p>{html_lib.escape(explanation)}</p>",
        suggested_tags=sol["tags"],
        suggested_difficulty=Difficulty(sol["difficulty"]),
        confidence=round(confidence, 3),
        raw_response={"first": first["raw"], "selfcheck": check["raw"],
                      "selfcheck_agree": agree, "usage": usage, "cost_usd": round(cost, 6)},
    ))
    q.correct_option_id = suggested.id
    q.answer_source = AnswerSource.ai_solved
    q.answer_confidence = round(confidence, 3)
    q.explanation_html = f"<p>{html_lib.escape(explanation)}</p>"
    q.status = QuestionStatus.pending_review
    db.flush()
    return {"question_id": str(q.id), "status": "solved",
            "answer_label": sol["answer_label"], "confidence": round(confidence, 3),
            "selfcheck_agree": agree, "cost_usd": round(cost, 6)}


def solve_batch(db: Session, questions: list[QuestionItem], provider: BaseProvider) -> dict:
    stats = {"total": len(questions), "solved": 0, "failed": 0,
             "low_confidence": 0, "cost_usd": 0.0, "results": []}
    for q in questions:
        r = solve_question(db, q, provider)
        stats["results"].append(r)
        if r["status"] == "solved":
            stats["solved"] += 1
            stats["cost_usd"] = round(stats["cost_usd"] + r["cost_usd"], 6)
            if r["confidence"] < CONFIDENCE_GATE:
                stats["low_confidence"] += 1
        else:
            stats["failed"] += 1
    db.commit()
    return stats
