"""EB-402 + EB-403 — Sinh đề từ kho câu ĐÃ DUYỆT (approved) theo template.

Nguyên tắc:
- Chỉ câu status=approved VÀ có đáp án mới được dùng.
- Câu thuộc đoạn văn (passage) không bao giờ bị tách khỏi đoạn của nó: các phần
  điền khuyết/đọc hiểu chọn theo NGUYÊN NHÓM đoạn; các phần khác chỉ lấy câu độc lập.
- Ưu tiên câu ít được dùng nhất (used_count) để đề không lặp lại một nhóm câu.
- Thiếu câu ở bất kỳ phần nào -> GenerationError liệt kê rõ phần nào thiếu bao nhiêu.
- EB-403: mỗi mã đề hoán vị thứ tự câu (nhóm đoạn di chuyển nguyên khối) và hoán vị
  phương án; nhãn đáp án đúng được PHÂN BỔ CÂN BẰNG (lệch nhau tối đa 1 câu).
"""
import random
import uuid as uuid_lib
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    Difficulty, Exam, ExamItem, ExamTemplate, ExamVersion, Option, PassageGroup,
    QuestionItem, QuestionStatus, QuestionTag, TemplateSection,
)

LABELS = ["A", "B", "C", "D"]


class GenerationError(Exception):
    def __init__(self, shortfalls: list[dict]):
        self.shortfalls = shortfalls
        detail = "; ".join(
            f"Phần '{s['section']}' cần {s['needed']} câu nhưng kho chỉ có {s['available']} câu phù hợp"
            for s in shortfalls)
        super().__init__(f"Không đủ câu đã duyệt để sinh đề: {detail}")


def _pool(db: Session, workspace_id, section: TemplateSection) -> list[QuestionItem]:
    q = (db.query(QuestionItem)
         .filter(QuestionItem.workspace_id == workspace_id,
                 QuestionItem.status == QuestionStatus.approved,
                 QuestionItem.question_type == section.question_type,
                 QuestionItem.correct_option_id.isnot(None)))
    if section.passage_type:
        q = q.filter(QuestionItem.passage_id.isnot(None))
    else:
        q = q.filter(QuestionItem.passage_id.is_(None))
    items = q.all()
    wanted_tags = (section.tag_filter or {}).get("tags") or []
    if wanted_tags:
        tag_map = defaultdict(set)
        for qt in db.query(QuestionTag).filter(
                QuestionTag.question_id.in_([i.id for i in items])).all():
            tag_map[qt.question_id].add(qt.tag_id)
        from app.models import Tag
        wanted_ids = {t.id for t in db.query(Tag).filter(Tag.code.in_(wanted_tags)).all()}
        items = [i for i in items if wanted_ids.issubset(tag_map[i.id])]
    return items


def _difficulty_targets(mix: dict, count: int) -> dict[str, int]:
    if not mix:
        return {}
    targets, assigned = {}, 0
    keys = [k for k in ("NB", "TH", "VD", "VDC") if mix.get(k)]
    for k in keys:
        targets[k] = int(mix[k] * count)
        assigned += targets[k]
    # phần dư do làm tròn: cộng vào mức có tỉ lệ lớn nhất
    while assigned < count and keys:
        k = max(keys, key=lambda x: mix[x])
        targets[k] += 1
        assigned += 1
    return targets


def _draw_standalone(pool: list[QuestionItem], section: TemplateSection,
                     rng: random.Random) -> list[QuestionItem] | None:
    """Chọn câu độc lập theo tỉ lệ độ khó; không đủ TỔNG số thì trả None (thiếu)."""
    need = section.question_count
    if len(pool) < need:
        return None
    targets = _difficulty_targets(section.difficulty_mix or {}, need)
    by_diff: dict[str, list[QuestionItem]] = defaultdict(list)
    for item in pool:
        by_diff[item.difficulty.value if item.difficulty else "TH"].append(item)
    chosen: list[QuestionItem] = []
    # Ưu tiên mức khó khan hiếm trước (VDC -> VD -> TH -> NB), trong mức: ít dùng nhất trước
    for diff in ("VDC", "VD", "TH", "NB"):
        want = targets.get(diff, 0)
        if want <= 0:
            continue
        cands = sorted(by_diff.get(diff, []), key=lambda x: (x.used_count, rng.random()))
        chosen.extend(cands[:want])
    if len(chosen) < need:  # mượn phần còn thiếu từ các mức khác (vẫn ưu tiên ít dùng)
        rest = [i for i in pool if i not in chosen]
        rest.sort(key=lambda x: (x.used_count, rng.random()))
        chosen.extend(rest[:need - len(chosen)])
    rng.shuffle(chosen)
    return chosen


def _draw_passage_groups(pool: list[QuestionItem], section: TemplateSection,
                         rng: random.Random) -> list[QuestionItem] | None:
    """Chọn NGUYÊN NHÓM đoạn cho tới khi đủ số câu; không ghép được đúng số -> None."""
    need = section.question_count
    groups: dict[str, list[QuestionItem]] = defaultdict(list)
    for item in pool:
        groups[str(item.passage_id)].append(item)
    ordered = sorted(groups.values(),
                     key=lambda g: (sum(x.used_count for x in g), rng.random()))
    chosen: list[QuestionItem] = []
    for g in ordered:
        g_sorted = sorted(g, key=lambda x: x.order_in_source)
        if len(chosen) + len(g_sorted) <= need:
            chosen.extend(g_sorted)
        if len(chosen) == need:
            return chosen
    # EB-406: không ghép vừa bằng nhóm nguyên -> cho phép dùng MỘT phần của một nhóm
    # (đoạn văn vẫn đi nguyên vẹn cùng các câu được chọn; các câu còn lại ở lại kho).
    # Ưu tiên nhóm lớn nhất còn đủ chỗ trống cần lấp.
    remaining = need - len(chosen)
    if remaining > 0:
        used_ids = {x.id for x in chosen}
        candidates = [sorted(g, key=lambda x: x.order_in_source)
                      for g in ordered
                      if len(g) >= remaining and g[0].id not in used_ids]
        if candidates:
            g = max(candidates, key=len)
            chosen.extend(g[:remaining])
            return chosen
    return None


def _snapshot(db: Session, item: QuestionItem, passage_cache: dict) -> dict:
    options = (db.query(Option).filter_by(question_id=item.id)
               .order_by(Option.position).all())
    correct = next((o.label for o in options if o.id == item.correct_option_id), None)
    passage = None
    if item.passage_id:
        if item.passage_id not in passage_cache:
            p = db.get(PassageGroup, item.passage_id)
            passage_cache[item.passage_id] = (
                {"content_html": p.content_html, "content_text": p.content_text,
                 "title": p.title} if p else None)
        passage = passage_cache[item.passage_id]
    return {
        "question_id": str(item.id), "question_type": item.question_type,
        "difficulty": item.difficulty.value if item.difficulty else None,
        "stem_html": item.stem_html, "stem_text": item.stem_text,
        "passage_id": str(item.passage_id) if item.passage_id else None,
        "passage": passage,
        "options": [{"label": o.label, "html": o.content_html, "text": o.content_text}
                    for o in options],
        "correct_label": correct, "explanation_html": item.explanation_html,
    }


def _balanced_version_items(blocks: list[list[dict]], rng: random.Random,
                            shuffle_order: bool) -> tuple[list[dict], dict]:
    """blocks: danh sách khối (1 khối = 1 nhóm đoạn hoặc 1 câu độc lập) ở dạng snapshot.
    Trả (items đã gán nhãn mới + correct_label mới, answer_balance)."""
    flat_blocks = [list(b) for b in blocks]
    if shuffle_order:
        rng.shuffle(flat_blocks)
    counts: Counter = Counter()
    out: list[dict] = []
    for block in flat_blocks:
        for snap in block:
            opts = list(snap["options"])
            correct_opt = next(o for o in opts if o["label"] == snap["correct_label"])
            others = [o for o in opts if o["label"] != snap["correct_label"]]
            rng.shuffle(others)
            # Nhãn đích cho đáp án đúng: nhãn đang ÍT xuất hiện nhất (cân bằng đáp án)
            target = min(LABELS[:len(opts)], key=lambda l: (counts[l], rng.random()))
            new_opts, new_correct = [], None
            oi = 0
            for slot, label in enumerate(LABELS[:len(opts)]):
                if label == target:
                    chosen_opt = correct_opt
                    new_correct = label
                else:
                    chosen_opt = others[oi]; oi += 1
                new_opts.append({"label": label, "html": chosen_opt["html"],
                                 "text": chosen_opt["text"]})
            counts[new_correct] += 1
            out.append({**snap, "options": new_opts, "correct_label": new_correct})
    return out, dict(counts)


def generate_exam(db: Session, *, workspace_id, template: ExamTemplate, title: str,
                  created_by, n_versions: int = 4, seed: int | None = None) -> Exam:
    rng = random.Random(seed)
    sections = (db.query(TemplateSection).filter_by(template_id=template.id)
                .order_by(TemplateSection.section_order).all())
    blocks: list[list[dict]] = []
    shortfalls: list[dict] = []
    passage_cache: dict = {}
    drawn_items: list[QuestionItem] = []
    for section in sections:
        pool = _pool(db, workspace_id, section)
        if section.passage_type:
            drawn = _draw_passage_groups(pool, section, rng)
            if drawn is None:
                available = len(pool)
                shortfalls.append({"section": section.name, "needed": section.question_count,
                                   "available": available})
                continue
            by_passage: dict[str, list[QuestionItem]] = defaultdict(list)
            for it in drawn:
                by_passage[str(it.passage_id)].append(it)
            for g in by_passage.values():
                blocks.append([_snapshot(db, it, passage_cache) for it in g])
                drawn_items.extend(g)
        else:
            drawn = _draw_standalone(pool, section, rng)
            if drawn is None:
                shortfalls.append({"section": section.name, "needed": section.question_count,
                                   "available": len(pool)})
                continue
            for it in drawn:
                blocks.append([_snapshot(db, it, passage_cache)])
            drawn_items.extend(drawn)
    if shortfalls:
        raise GenerationError(shortfalls)

    exam = Exam(workspace_id=workspace_id, template_id=template.id, title=title,
                grade=template.grade, duration_minutes=template.duration_minutes,
                created_by=created_by)
    db.add(exam); db.flush()
    for v in range(n_versions):
        code = f"{v + 1:03d}"
        items, balance = _balanced_version_items(blocks, rng, shuffle_order=(v > 0))
        version = ExamVersion(exam_id=exam.id, code=code, answer_balance=balance)
        db.add(version); db.flush()
        for pos, snap in enumerate(items, 1):
            db.add(ExamItem(
                exam_version_id=version.id,
                question_id=uuid_lib.UUID(snap["question_id"]),
                passage_id=uuid_lib.UUID(snap["passage_id"]) if snap["passage_id"] else None,
                position=pos,
                shuffled_correct_label=snap["correct_label"], snapshot_json=snap))
    now = datetime.now(timezone.utc)
    for it in drawn_items:
        it.used_count = (it.used_count or 0) + 1
        it.last_used_at = now
    db.commit()
    db.refresh(exam)
    return exam
