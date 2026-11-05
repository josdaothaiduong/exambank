"""EL-202/EL-204 — Pipeline bẻ hạt học tập + hậu-đề + biến thể (Sprint 2).

Tái dùng hạ tầng AI của ExamBank (app/ai/provider.py: get_provider, cost_usd,
kỷ luật ép JSON + retry) — KHÔNG viết pipeline AI thứ hai. Điểm khác với
pipeline giải đề (app/ai/pipeline.py): đầu ra là nội dung học (atom + hậu-đề
+ biến thể), luôn ở trạng thái pending_review chờ GV duyệt (quy tắc R1 của
DB-API-SPEC: chưa `approved` thì không gì tới được HS).

Ràng buộc cứng:
- Sinh 1 LẦN cho 1 câu: chạy lại khi đã có nội dung -> trả bản cũ, không gọi
  AI, không sinh trùng (trừ force=True do GV bấm sinh lại có chủ đích).
- Tôn trọng quyết định GV: atom đã reject/approved KHÔNG bị ghi đè khi sinh
  lại — dedup_hash (workspace, question, headword chuẩn hoá) là khoá chống
  trùng; atom trùng khoá bị bỏ qua nguyên trạng.
- Trần 3 atom/câu; cấp đề: trần 120 atom/đề.
- Validate chặt toàn bộ JSON trước khi lưu bất cứ thứ gì: hỏng -> retry 1 lần
  -> job 'failed' + error_log, KHÔNG lưu rác.
- Mọi lần gọi AI đều ghi sổ: ai_generation_jobs (spec 2.20) + api_usage_logs
  (bảng L5 EL-007 — hệ thống không có bảng tên 'ai_usage_logs').
- Kết quả biến thể CHƯA đẩy vào FSRS ở sprint này (Sprint 3 mới nối thẻ ôn).
"""
import hashlib
import html as html_lib
import json
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai.provider import ProviderError, get_provider
from app.config import settings
from app.models import (
    AIGenerationJob, ApiUsageLog, AtomSource, AtomTag, LearningAtom, Option,
    PassageGroup, PostTestContent, QuestionItem, QuestionStatus, QuestionTag,
    VariantItem, VariantOption,
)

MAX_ATOMS_PER_QUESTION = 3
MAX_ATOMS_PER_EXAM = 120

ATOM_TYPES = {"vocab", "collocation", "phrasal_verb", "grammar_point",
              "reading_skill", "distractor_trap", "discourse", "paraphrase"}
SOURCE_ROLES = {"correct_answer", "distractor", "passage_text", "stem",
                "paraphrase_target"}
ERROR_CODES = {"LEX", "COL", "L1", "GRA", "ABS", "LOG", "SPD"}
PRIORITIES = {"P1", "P2", "P3"}

_TRUSTED_PROVENANCE = {"red_text": "red_text", "highlight": "highlight",
                       "answer_key_table": "answer_key_table",
                       "teacher_manual": "teacher_manual"}

CONTENT_SYSTEM_PROMPT = """Bạn là giáo viên Tiếng Anh THPT Việt Nam (Global Success).
Nhiệm vụ: bẻ 1 câu trắc nghiệm ĐÃ CÓ đáp án đúng được duyệt thành nội dung học hậu-kiểm-tra.
Trả DUY NHẤT một JSON đúng cấu trúc:
{"atoms": [{"headword": "...", "atom_type": "vocab|collocation|phrasal_verb|grammar_point|reading_skill|distractor_trap|discourse|paraphrase",
  "front_text": "mặt hỏi, không chứa đáp án", "back_text": "mặt đáp án + giải thích ngắn",
  "meaning_vi": "nghĩa Việt 1 dòng", "meaning_en": null, "example_sentence": "câu ví dụ NGOÀI câu gốc",
  "priority": "P1|P2|P3", "common_error_code": "LEX|COL|L1|GRA|ABS|LOG|SPD hoặc null",
  "source_role": "correct_answer|distractor|passage_text|stem|paraphrase_target", "confidence": 0.9}],
 "p1_variants": [{"atom_index": 0, "stem_text": "...", "options": [{"label": "A", "text": "..."}], "correct_label": "A", "confidence": 0.9}],
 "post_test": {"error_code": "L1", "why_wrong": "...", "diagnosis_options": [{"key": "surface_match", "text": "..."}],
  "correct_diagnosis_key": "surface_match", "cue": "1 câu", "rule": "quy tắc 1 câu", "why_correct": "...",
  "minimal_pair": [{"key": "s1", "text": "...", "is_correct": true}], "confidence": 0.9}}
Quy tắc: tối đa 3 atoms; atoms suy ra từ đáp án đúng và các distractor THẬT của câu,
không bịa đáp án mới; ít nhất 1 biến thể p1 cho atom đầu tiên; diagnosis_options >= 2;
minimal_pair có ít nhất 1 câu đúng."""

VARIANT_SYSTEM_PROMPT = """Bạn là giáo viên Tiếng Anh THPT Việt Nam.
Nhiệm vụ: tạo 1 câu biến thể MỚI (ngữ cảnh khác hẳn câu gốc) để kiểm tra đúng hạt học tập được cung cấp.
Trả DUY NHẤT một JSON: {"stem_text": "...", "options": [{"label": "A", "text": "..."}],
"correct_label": "A", "confidence": 0.9}
Quy tắc: biến thể kiểm tra đúng headword của atom; đáp án đúng phải nằm trong options;
không dùng lại câu gốc/đoạn văn gốc."""


class ContentValidationError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _strip_html(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"<[^>]+>", "", s).strip()


def provenance_for(q: QuestionItem) -> tuple[str, bool]:
    """(answer_provenance cho atom/nội dung, needs_teacher_confirmation)."""
    src = q.answer_source.value if q.answer_source else "unknown"
    if src in _TRUSTED_PROVENANCE:
        return _TRUSTED_PROVENANCE[src], False
    # ai_solved / unknown / tín hiệu vật lý chưa có giá trị CK tương ứng
    # (bold_underline, marker_star) -> ai_inferred + bắt GV xác nhận.
    return "ai_inferred", True


def question_payload(db: Session, q: QuestionItem) -> dict:
    options = (db.query(Option).filter_by(question_id=q.id)
               .order_by(Option.position).all())
    correct = next((o for o in options if o.id == q.correct_option_id), None)
    passage_text = None
    if q.passage_id:
        p = db.get(PassageGroup, q.passage_id)
        passage_text = p.content_text if p else None
    return {
        "question_id": str(q.id),
        "question_type": q.question_type,
        "stem_text": q.stem_text,
        "passage_text": passage_text,
        "options": [{"label": o.label, "text": o.content_text} for o in options],
        "correct_label": correct.label if correct else None,
        "correct_text": correct.content_text if correct else None,
        "distractors": [{"label": o.label, "text": o.content_text}
                        for o in options if correct is None or o.id != correct.id],
        "explanation_text": _strip_html(q.explanation_html),
    }


# ------------------------------------------------------------------ validate
def _req_str(d: dict, key: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ContentValidationError(f"Thiếu/không hợp lệ trường '{key}'")
    return v


def _opt_conf(d: dict) -> float:
    c = d.get("confidence", 0.8)
    try:
        c = float(c)
    except (TypeError, ValueError):
        raise ContentValidationError("confidence không phải số")
    if not 0.0 <= c <= 1.0:
        raise ContentValidationError("confidence ngoài khoảng 0-1")
    return c


def _validate_options(raw) -> tuple[list[dict], str]:
    if not isinstance(raw, list) or len(raw) < 2:
        raise ContentValidationError("options phải có ít nhất 2 phương án")
    options, labels = [], set()
    for o in raw:
        if not isinstance(o, dict):
            raise ContentValidationError("option không phải object")
        label = _req_str(o, "label")
        if label in labels:
            raise ContentValidationError(f"label trùng: {label}")
        labels.add(label)
        options.append({"label": label, "text": _req_str(o, "text")})
    return options, labels


def validate_content(data, max_atoms: int = MAX_ATOMS_PER_QUESTION) -> dict:
    if not isinstance(data, dict):
        raise ContentValidationError("Kết quả AI không phải JSON object")
    atoms_raw = data.get("atoms")
    if not isinstance(atoms_raw, list) or not atoms_raw:
        raise ContentValidationError("atoms rỗng")
    if len(atoms_raw) > max_atoms:
        raise ContentValidationError(f"atoms vượt trần {max_atoms}/câu")
    atoms = []
    for a in atoms_raw:
        if not isinstance(a, dict):
            raise ContentValidationError("atom không phải object")
        atom = {
            "headword": _req_str(a, "headword"),
            "atom_type": _req_str(a, "atom_type"),
            "front_text": _req_str(a, "front_text"),
            "back_text": _req_str(a, "back_text"),
            "meaning_vi": _req_str(a, "meaning_vi"),
            "meaning_en": a.get("meaning_en") if isinstance(a.get("meaning_en"), str) else None,
            "example_sentence": _req_str(a, "example_sentence"),
            "priority": a.get("priority", "P2"),
            "common_error_code": a.get("common_error_code"),
            "source_role": _req_str(a, "source_role"),
            "confidence": _opt_conf(a),
        }
        if atom["atom_type"] not in ATOM_TYPES:
            raise ContentValidationError(f"atom_type sai: {atom['atom_type']}")
        if atom["priority"] not in PRIORITIES:
            raise ContentValidationError(f"priority sai: {atom['priority']}")
        if atom["source_role"] not in SOURCE_ROLES:
            raise ContentValidationError(f"source_role sai: {atom['source_role']}")
        if atom["common_error_code"] is not None and atom["common_error_code"] not in ERROR_CODES:
            raise ContentValidationError(f"common_error_code sai: {atom['common_error_code']}")
        atoms.append(atom)

    variants = []
    for v in data.get("p1_variants") or []:
        if not isinstance(v, dict):
            raise ContentValidationError("p1_variant không phải object")
        idx = v.get("atom_index")
        if not isinstance(idx, int) or not 0 <= idx < len(atoms):
            raise ContentValidationError("p1_variant atom_index sai")
        options, labels = _validate_options(v.get("options"))
        correct_label = _req_str(v, "correct_label")
        if correct_label not in labels:
            raise ContentValidationError("p1_variant correct_label không thuộc options")
        variants.append({"atom_index": idx, "stem_text": _req_str(v, "stem_text"),
                         "options": options, "correct_label": correct_label,
                         "confidence": _opt_conf(v)})

    pt = data.get("post_test")
    if not isinstance(pt, dict):
        raise ContentValidationError("thiếu post_test")
    diag_raw = pt.get("diagnosis_options")
    if not isinstance(diag_raw, list) or len(diag_raw) < 2:
        raise ContentValidationError("diagnosis_options phải có ít nhất 2 lựa chọn")
    diag, diag_keys = [], set()
    for d in diag_raw:
        if not isinstance(d, dict):
            raise ContentValidationError("diagnosis option không phải object")
        key = _req_str(d, "key")
        if key in diag_keys:
            raise ContentValidationError(f"diagnosis key trùng: {key}")
        diag_keys.add(key)
        diag.append({"key": key, "text": _req_str(d, "text")})
    correct_diag = _req_str(pt, "correct_diagnosis_key")
    if correct_diag not in diag_keys:
        raise ContentValidationError("correct_diagnosis_key không thuộc diagnosis_options")
    pair_raw = pt.get("minimal_pair")
    if not isinstance(pair_raw, list) or not pair_raw:
        raise ContentValidationError("minimal_pair rỗng")
    pair, pair_keys = [], set()
    for s in pair_raw:
        if not isinstance(s, dict) or not isinstance(s.get("is_correct"), bool):
            raise ContentValidationError("minimal_pair item sai định dạng")
        key = _req_str(s, "key")
        if key in pair_keys:
            raise ContentValidationError(f"minimal_pair key trùng: {key}")
        pair_keys.add(key)
        pair.append({"key": key, "text": _req_str(s, "text"),
                     "is_correct": s["is_correct"]})
    if not any(s["is_correct"] for s in pair):
        raise ContentValidationError("minimal_pair phải có ít nhất 1 câu đúng")
    error_code = pt.get("error_code")
    if error_code is not None and error_code not in ERROR_CODES:
        raise ContentValidationError(f"post_test error_code sai: {error_code}")
    post_test = {
        "error_code": error_code,
        "why_wrong": _req_str(pt, "why_wrong"),
        "diagnosis_options": diag,
        "correct_diagnosis_key": correct_diag,
        "cue": _req_str(pt, "cue"),
        "rule": _req_str(pt, "rule"),
        "why_correct": _req_str(pt, "why_correct"),
        "minimal_pair": pair,
    }
    return {"atoms": atoms, "p1_variants": variants, "post_test": post_test,
            "post_test_confidence": _opt_conf(pt)}


def validate_variant(data) -> dict:
    if not isinstance(data, dict):
        raise ContentValidationError("Biến thể không phải JSON object")
    options, labels = _validate_options(data.get("options"))
    correct_label = _req_str(data, "correct_label")
    if correct_label not in labels:
        raise ContentValidationError("correct_label không thuộc options của biến thể")
    return {"stem_text": _req_str(data, "stem_text"), "options": options,
            "correct_label": correct_label, "confidence": _opt_conf(data)}


# ------------------------------------------------------------------ ghi sổ
def _record_usage(db: Session, *, workspace_id, user_id, provider, endpoint_kind,
                  usage: dict, cost: float):
    db.add(ApiUsageLog(
        workspace_id=workspace_id, provider=provider.name,
        endpoint_kind=endpoint_kind, user_id=user_id,
        units=(usage.get("input_tokens", 0) + usage.get("output_tokens", 0)),
        est_cost=round(cost, 6)))


def _call_with_retry(provider, *, system: str, user: str, validate):
    """Gọi provider + validate; sai schema thì gọi lại 1 lần (pattern ai.py)."""
    last_err: Exception | None = None
    usage_total = {"input_tokens": 0, "output_tokens": 0}
    for _ in range(2):
        res = provider.generate_json(system=system, user=user)
        for k in usage_total:
            usage_total[k] += res["usage"].get(k, 0)
        try:
            return validate(res["data"]), usage_total
        except ContentValidationError as e:
            last_err = e
    raise ContentValidationError(f"JSON không đạt sau 2 lần gọi: {last_err}")


def _dedup_hash(workspace_id, question_id, headword: str) -> str:
    raw = f"{workspace_id}:{question_id}:{headword.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _p(text: str) -> str:
    return f"<p>{html_lib.escape(text)}</p>"


def _insert_variant(db: Session, *, workspace_id, parent_atom_id, tier: str,
                    vdata: dict, origin: str, provenance: str, created_by) -> VariantItem:
    var = VariantItem(
        workspace_id=workspace_id, parent_atom_id=parent_atom_id,
        variant_tier=tier, stem_html=_p(vdata["stem_text"]),
        stem_text=vdata["stem_text"], status="pending_review", origin=origin,
        ai_confidence=vdata["confidence"], answer_provenance=provenance,
        created_by=created_by)
    db.add(var)
    db.flush()
    for pos, o in enumerate(vdata["options"]):
        opt = VariantOption(variant_id=var.id, label=o["label"],
                            content_html=_p(o["text"]), content_text=o["text"],
                            position=pos)
        db.add(opt)
        db.flush()
        if o["label"] == vdata["correct_label"]:
            var.correct_option_id = opt.id
    db.flush()
    return var


# ------------------------------------------------------------------ EL-202
def generate_for_question(db: Session, q: QuestionItem, teacher, *,
                          provider=None, max_atoms: int = MAX_ATOMS_PER_QUESTION,
                          force: bool = False, exam_atom_budget: int | None = None) -> dict:
    """Sinh atom + hậu-đề + biến thể P1(T1) cho 1 câu. Trả dict kết quả/job.

    exam_atom_budget: số atom mới tối đa còn được tạo (trần cấp đề) — None = không giới hạn.
    """
    provider = provider or get_provider(settings)
    existing_atoms = (db.query(LearningAtom)
                      .filter_by(source_question_id=q.id).all())
    existing_content = (db.query(PostTestContent)
                        .filter_by(question_id=q.id).one_or_none())
    if existing_atoms and existing_content is not None and not force:
        return {"status": "existing", "job_id": None,
                "atom_ids": [str(a.id) for a in existing_atoms],
                "created_atom_ids": [], "skipped_atom_ids": [],
                "post_test_content_id": str(existing_content.id)}

    job = AIGenerationJob(workspace_id=q.workspace_id, kind="atom_extract",
                          source_question_id=q.id, model=provider.model,
                          status="running")
    db.add(job)
    db.flush()
    payload = question_payload(db, q)
    user_prompt = (
        "TASK:atom_extract\n"
        "Hãy bẻ câu sau thành atoms + hậu-đề + biến thể P1 theo cấu trúc đã quy định.\n"
        f"CÂU HỎI: {payload['stem_text']}\n"
        + "".join(f"{o['label']}. {o['text']}\n" for o in payload["options"])
        + f"ĐÁP ÁN ĐÚNG ĐÃ DUYỆT: {payload['correct_label']}. {payload['correct_text']}\n"
        + "DATA_JSON:" + json.dumps(payload, ensure_ascii=False))
    try:
        content, usage = _call_with_retry(
            provider, system=CONTENT_SYSTEM_PROMPT, user=user_prompt,
            validate=lambda d: validate_content(d, max_atoms))
    except (ProviderError, ContentValidationError) as e:
        job.status = "failed"
        job.error_log = [{"question_id": str(q.id), "error": str(e)}]
        job.finished_at = _now()
        db.flush()
        return {"status": "failed", "job_id": str(job.id), "error": str(e),
                "atom_ids": [str(a.id) for a in existing_atoms],
                "created_atom_ids": [], "skipped_atom_ids": [],
                "post_test_content_id": str(existing_content.id) if existing_content else None}

    cost = provider.cost_usd(usage)
    job.tokens_in = usage["input_tokens"]
    job.tokens_out = usage["output_tokens"]
    job.cost_usd_estimate = round(cost, 6)
    _record_usage(db, workspace_id=q.workspace_id, user_id=teacher.id,
                  provider=provider, endpoint_kind="atom_extract",
                  usage=usage, cost=cost)

    origin = "rule_based" if provider.name == "demo" else "ai_generated"
    provenance, needs_confirm = provenance_for(q)
    atom_by_index: dict[int, LearningAtom] = {}
    created_ids, skipped_ids = [], []
    budget = exam_atom_budget
    for idx, adata in enumerate(content["atoms"]):
        dh = _dedup_hash(q.workspace_id, q.id, adata["headword"])
        dup = (db.query(LearningAtom)
               .filter_by(workspace_id=q.workspace_id, dedup_hash=dh).one_or_none())
        if dup is not None:
            # Đã có (kể cả rejected/approved): tôn trọng trạng thái GV đã quyết.
            atom_by_index[idx] = dup
            skipped_ids.append(str(dup.id))
            continue
        if budget is not None and budget <= 0:
            skipped_ids.append("budget_exceeded")
            continue
        atom = LearningAtom(
            workspace_id=q.workspace_id, headword=adata["headword"],
            atom_type=adata["atom_type"], front_html=_p(adata["front_text"]),
            front_text=adata["front_text"], back_html=_p(adata["back_text"]),
            back_text=adata["back_text"], meaning_vi=adata["meaning_vi"],
            meaning_en=adata["meaning_en"],
            example_sentence=adata["example_sentence"],
            source_sentence=q.stem_text, priority=adata["priority"],
            common_error_code=adata["common_error_code"],
            source_question_id=q.id, source_passage_id=q.passage_id,
            status="pending_review", origin=origin, answer_provenance=provenance,
            ai_confidence=adata["confidence"],
            needs_teacher_confirmation=needs_confirm, dedup_hash=dh,
            created_by=teacher.id)
        db.add(atom)
        db.flush()
        db.add(AtomSource(atom_id=atom.id, question_id=q.id,
                          source_exam_id=q.source_exam_id,
                          source_role=adata["source_role"]))
        for qt in db.query(QuestionTag).filter_by(question_id=q.id).all():
            db.add(AtomTag(atom_id=atom.id, tag_id=qt.tag_id, is_ai_suggested=True))
        atom_by_index[idx] = atom
        created_ids.append(str(atom.id))
        if budget is not None:
            budget -= 1

    # Biến thể P1 (= tier T1) cho các atom vừa có — không sinh trùng cùng stem.
    for vdata in content["p1_variants"]:
        atom = atom_by_index.get(vdata["atom_index"])
        if atom is None:
            continue
        dup_var = (db.query(VariantItem)
                   .filter_by(parent_atom_id=atom.id, variant_tier="T1",
                              stem_text=vdata["stem_text"]).first())
        if dup_var is not None:
            continue
        _insert_variant(db, workspace_id=q.workspace_id, parent_atom_id=atom.id,
                        tier="T1", vdata=vdata, origin=origin,
                        provenance=provenance, created_by=teacher.id)

    # Nội dung hậu-đề: câu đã rejected/approved -> giữ nguyên quyết định GV.
    if existing_content is not None and existing_content.status in ("approved", "rejected"):
        content_id = str(existing_content.id)
    elif existing_content is not None:
        existing_content.content_json = content["post_test"]
        existing_content.ai_confidence = content["post_test_confidence"]
        db.flush()
        content_id = str(existing_content.id)
    else:
        pc = PostTestContent(
            workspace_id=q.workspace_id, question_id=q.id,
            content_json=content["post_test"], status="pending_review",
            origin=origin, answer_provenance=provenance,
            ai_confidence=content["post_test_confidence"],
            needs_teacher_confirmation=needs_confirm, created_by=teacher.id)
        db.add(pc)
        db.flush()
        content_id = str(pc.id)

    job.status = "succeeded"
    job.finished_at = _now()
    db.flush()
    return {"status": "succeeded" if created_ids or not existing_atoms else "existing",
            "job_id": str(job.id),
            "atom_ids": [str(a.id) for a in
                         db.query(LearningAtom).filter_by(source_question_id=q.id).all()],
            "created_atom_ids": created_ids, "skipped_atom_ids": skipped_ids,
            "post_test_content_id": content_id}


def generate_for_exam(db: Session, exam, teacher, *, provider=None,
                      force: bool = False) -> dict:
    """Sinh cho mọi câu approved + có đáp án của 1 đề gốc; trần 120 atom/đề."""
    provider = provider or get_provider(settings)
    questions = (db.query(QuestionItem).filter_by(source_exam_id=exam.id)
                 .order_by(QuestionItem.order_in_source.is_(None),
                           QuestionItem.order_in_source,
                           QuestionItem.created_at).all())
    eligible = [q for q in questions
                if q.status == QuestionStatus.approved and q.correct_option_id]
    existing_count = 0
    if eligible:
        existing_count = (db.query(LearningAtom)
                          .filter(LearningAtom.source_question_id.in_(
                              [q.id for q in eligible])).count())
    results = []
    created_total = 0
    for q in eligible:
        budget = MAX_ATOMS_PER_EXAM - existing_count - created_total
        r = generate_for_question(db, q, teacher, provider=provider,
                                  force=force, exam_atom_budget=max(budget, 0))
        results.append({"question_id": str(q.id), **r})
        created_total += len(r.get("created_atom_ids", []))
    return {"source_exam_id": str(exam.id), "eligible_questions": len(eligible),
            "atoms_before": existing_count, "atoms_created": created_total,
            "atoms_total": existing_count + created_total,
            "cap": MAX_ATOMS_PER_EXAM, "results": results}


# ------------------------------------------------------------------ EL-204
def generate_variant_p2(db: Session, atom: LearningAtom, teacher, *,
                        provider=None, force: bool = False) -> dict:
    """Sinh biến thể P2 (= tier T2, ngữ cảnh mới) cho 1 atom."""
    provider = provider or get_provider(settings)
    existing = (db.query(VariantItem)
                .filter_by(parent_atom_id=atom.id, variant_tier="T2").all())
    if existing and not force:
        return {"status": "existing", "job_id": None,
                "variant_id": str(existing[0].id)}
    job = AIGenerationJob(workspace_id=atom.workspace_id, kind="variant_gen",
                          source_atom_id=atom.id,
                          source_question_id=atom.source_question_id,
                          model=provider.model, status="running")
    db.add(job)
    db.flush()
    q = db.get(QuestionItem, atom.source_question_id)
    distractor_texts = []
    if q is not None:
        distractor_texts = [o.content_text for o in
                            db.query(Option).filter_by(question_id=q.id)
                            .order_by(Option.position).all()
                            if o.id != q.correct_option_id]
    payload = {"atom_id": str(atom.id), "headword": atom.headword,
               "atom_type": atom.atom_type,
               "example_sentence": atom.example_sentence,
               "source_stem_text": q.stem_text if q else "",
               "distractor_texts": distractor_texts}
    user_prompt = ("TASK:variant_gen\nTạo 1 biến thể ngữ cảnh mới cho atom sau.\n"
                   f"HEADWORD: {atom.headword}\n"
                   "DATA_JSON:" + json.dumps(payload, ensure_ascii=False))
    try:
        vdata, usage = _call_with_retry(
            provider, system=VARIANT_SYSTEM_PROMPT, user=user_prompt,
            validate=validate_variant)
    except (ProviderError, ContentValidationError) as e:
        job.status = "failed"
        job.error_log = [{"atom_id": str(atom.id), "error": str(e)}]
        job.finished_at = _now()
        db.flush()
        return {"status": "failed", "job_id": str(job.id), "error": str(e),
                "variant_id": str(existing[0].id) if existing else None}
    cost = provider.cost_usd(usage)
    job.tokens_in = usage["input_tokens"]
    job.tokens_out = usage["output_tokens"]
    job.cost_usd_estimate = round(cost, 6)
    _record_usage(db, workspace_id=atom.workspace_id, user_id=teacher.id,
                  provider=provider, endpoint_kind="variant_gen",
                  usage=usage, cost=cost)
    origin = "rule_based" if provider.name == "demo" else "ai_generated"
    dup = (db.query(VariantItem)
           .filter_by(parent_atom_id=atom.id, variant_tier="T2",
                      stem_text=vdata["stem_text"]).first())
    if dup is not None:
        job.status = "succeeded"
        job.finished_at = _now()
        db.flush()
        return {"status": "existing", "job_id": str(job.id),
                "variant_id": str(dup.id)}
    var = _insert_variant(db, workspace_id=atom.workspace_id,
                          parent_atom_id=atom.id, tier="T2", vdata=vdata,
                          origin=origin, provenance=atom.answer_provenance,
                          created_by=teacher.id)
    job.status = "succeeded"
    job.finished_at = _now()
    db.flush()
    return {"status": "succeeded", "job_id": str(job.id),
            "variant_id": str(var.id)}
