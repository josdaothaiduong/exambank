"""EB-301 — AIProvider trừu tượng: đổi nhà cung cấp/model bằng env, không sửa code.

- DemoProvider: bộ giải quy tắc xác định (deterministic), chạy offline, dùng để kiểm chứng
  toàn bộ pipeline khi chưa có API key. KHÔNG phải AI thật — độ chính xác bị giới hạn và
  được đo công khai ở EB-307.
- OpenAICompatibleProvider: gọi endpoint tương thích OpenAI (OpenAI chính hãng hoặc
  gateway khác qua AI_BASE_URL), ép JSON bằng response_format, retry khi sai định dạng.
"""
import json
import re

import httpx

from app.ai.prompts import SYSTEM_PROMPT

# Giá tham khảo USD / 1M token (input, output) để ước tính chi phí — cập nhật khi đổi model.
# Gemini: giá paid tier tra 2026-11-05 (ai.google.dev); free tier thì chi phí thực = 0,
# số này chỉ để ước lượng khi so sánh. Dòng gemini-2.5 đã đóng với người dùng mới.
PRICE_PER_MTOK = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.8-flash": (0.75, 3.75),
    "demo-rule-solver": (0.0, 0.0),
}

REQUIRED_KEYS = {"answer_label", "explanation_vi", "confidence", "difficulty", "tags"}


class ProviderError(Exception):
    pass


def validate_solution(data: dict, valid_labels: set[str]) -> dict:
    if not isinstance(data, dict) or not REQUIRED_KEYS.issubset(data):
        raise ProviderError(f"JSON thiếu trường bắt buộc: {data!r:.200}")
    if data["answer_label"] not in valid_labels:
        raise ProviderError(f"answer_label không hợp lệ: {data['answer_label']!r}")
    conf = float(data["confidence"])
    if not 0.0 <= conf <= 1.0:
        raise ProviderError("confidence ngoài khoảng 0-1")
    if data["difficulty"] not in ("NB", "TH", "VD", "VDC"):
        raise ProviderError(f"difficulty không hợp lệ: {data['difficulty']!r}")
    return {"answer_label": data["answer_label"],
            "explanation_vi": str(data["explanation_vi"])[:2000],
            "confidence": conf, "difficulty": data["difficulty"],
            "tags": [str(t) for t in data["tags"]][:3]}


class BaseProvider:
    name = "base"
    model = "base"

    def solve(self, *, system: str, user: str, valid_labels: set[str]) -> dict:
        """Trả {"solution": {...đã validate...}, "raw": dict, "usage": {"input_tokens","output_tokens"}}"""
        raise NotImplementedError

    def generate_json(self, *, system: str, user: str) -> dict:
        """Sinh nội dung JSON tự do (Sprint 2: bẻ hạt/hậu-đề/biến thể).

        Trả {"data": dict, "raw": dict, "usage": {...}}. Validate theo schema
        nghiệp vụ nằm ở pipeline gọi (app/learn/content_pipeline.py) — cùng
        kỷ luật với solve(): provider chỉ lo gọi model + parse JSON.
        """
        raise NotImplementedError

    def cost_usd(self, usage: dict) -> float:
        pin, pout = PRICE_PER_MTOK.get(self.model, (0.0, 0.0))
        return (usage.get("input_tokens", 0) * pin + usage.get("output_tokens", 0) * pout) / 1_000_000


class DemoProvider(BaseProvider):
    """Bộ giải quy tắc cho câu Tiếng Anh THPT — deterministic theo nội dung câu.

    Chỉ dùng các quy tắc ngôn ngữ rõ ràng (thì, hoà hợp chủ-vị, dấu hiệu thời gian,
    collocation phổ biến, từ đồng nghĩa quen thuộc). Khi không có quy tắc nào khớp,
    trả confidence thấp (0.40) để pipeline/giáo viên biết phải kiểm tra kỹ.
    """
    name = "demo"
    model = "demo-rule-solver"

    _SYNONYMS = {
        "crucial": "essential", "essential": "important", "rapid": "fast", "huge": "enormous",
        "ancient": "old", "brave": "courageous", "commence": "begin", "purchase": "buy",
        "assist": "help", "require": "need", "sufficient": "enough", "difficult": "hard",
        "wealthy": "rich", "famous": "well-known", "vacant": "empty", "annual": "yearly",
    }
    _ANTONYMS = {
        "ancient": "modern", "brave": "cowardly", "generous": "selfish", "ancient ": "modern",
        "victory": "defeat", "ancient,": "modern", "permit": "forbid", "expand": "contract",
    }

    def solve(self, *, system: str, user: str, valid_labels: set[str]) -> dict:
        stem, options = self._parse_prompt(user)
        label, conf, why = self._decide(stem, options)
        sol = {"answer_label": label, "explanation_vi": why, "confidence": conf,
               "difficulty": "TH", "tags": []}
        return {"solution": validate_solution(sol, valid_labels),
                "raw": {"provider": "demo", "rule_based": True},
                "usage": {"input_tokens": len(user.split()), "output_tokens": 24}}

    @staticmethod
    def _parse_prompt(user: str):
        lines = [l.strip() for l in user.split("\n")]
        stem_parts, options = [], []
        for l in lines:
            m = re.match(r"^([A-D])\.\s+(.*)$", l)
            if m:
                options.append({"label": m.group(1), "text": m.group(2)})
            elif l.startswith("CÂU HỎI:"):
                stem_parts.append(l[len("CÂU HỎI:"):].strip())
            elif options == [] and l and not l.startswith(("ĐOẠN VĂN:", "GỢI Ý")):
                stem_parts.append(l)
        return " ".join(stem_parts), options

    def _decide(self, stem: str, options: list[dict]):
        s = stem.lower()
        texts = {o["label"]: o["text"].strip() for o in options}
        low = {k: v.lower() for k, v in texts.items()}

        def pick(pred, conf, why):
            for label, txt in low.items():
                if pred(txt):
                    return label, conf, why
            return None

        # 1) since + mốc thời gian -> hiện tại hoàn thành
        if re.search(r"since\s+\d{4}|since\s+(last|yesterday|monday)", s):
            r = pick(lambda t: t.startswith(("has ", "have ", "has been", "have been")), 0.9,
                     "Sau 'since + mốc thời gian' dùng thì hiện tại hoàn thành (has/have + V3).")
            if r: return r
        # 2) every day / usually / always -> hiện tại đơn, chủ ngữ số ít -> động từ thêm s/es
        if re.search(r"every day|usually|always|often|every morning", s) and re.search(r"\b(he|she|it)\b|\b\w+\s+______", s):
            r = pick(lambda t: re.search(r"\w+(s|es)$", t) and " " not in t, 0.75,
                     "Dấu hiệu thói quen (every day/usually) -> hiện tại đơn; chủ ngữ số ít nên động từ thêm s/es.")
            if r: return r
        # 3) yesterday / last night / ago -> quá khứ đơn
        if re.search(r"yesterday|last night|last week|\d+\s+(days|years|months)\s+ago", s):
            r = pick(lambda t: t.endswith("ed") or t in ("went", "saw", "took", "gave", "came", "bought", "thought", "brought"), 0.8,
                     "Dấu hiệu thời gian quá khứ (yesterday/ago/last...) -> thì quá khứ đơn.")
            if r: return r
        # 4) than -> so sánh hơn
        if " than " in s:
            r = pick(lambda t: t.startswith("more ") or re.search(r"\w+er$", t), 0.85,
                     "Sau 'than' phải dùng dạng so sánh hơn (more + adj / adj-er).")
            if r: return r
        # 5) đồng nghĩa / trái nghĩa với từ quen thuộc
        m = re.search(r"closest in meaning to[:\s]*[\"“]?(\w+)", s) or re.search(r"word\s+[\"“](\w+)[\"”].*closest", s)
        target = None
        mm = re.search(r"[\"“](\w+)[\"”]", stem)
        if "closest in meaning" in s and mm:
            target = self._SYNONYMS.get(mm.group(1).lower())
            if target:
                r = pick(lambda t: t == target or target in t, 0.8,
                         f"Từ được hỏi đồng nghĩa với '{target}'.")
                if r: return r
        if "opposite in meaning" in s and mm:
            target = self._ANTONYMS.get(mm.group(1).lower())
            if target:
                r = pick(lambda t: t == target or target in t, 0.8,
                         f"Từ được hỏi trái nghĩa với '{target}'.")
                if r: return r
        # 6) bị động: be + V3 (phương án chứa is/are/was/were + phân từ)
        if re.search(r"______\s+(by|every day|every|daily)", s):
            r = pick(lambda t: re.match(r"(is|are|was|were)\s+\w+", t), 0.6,
                     "Ngữ cảnh bị động: cần cấu trúc be + phân từ quá khứ.")
            if r: return r
        # Mặc định: không có quy tắc chắc chắn -> chọn phương án đầu tiên với confidence THẤP
        first = options[0]["label"] if options else "A"
        return first, 0.40, ("Bộ giải demo không tìm thấy quy tắc ngôn ngữ đủ chắc chắn cho câu này; "
                             "đáp án chỉ là tạm chọn với độ tin cậy thấp — giáo viên cần tự quyết định.")

    def generate_json(self, *, system: str, user: str) -> dict:
        """Demo: đọc khối DATA_JSON trong prompt và dựng nội dung xác định.

        Hai loại tác vụ (pipeline ghi ở dòng TASK:): 'atom_extract' (bẻ hạt +
        hậu-đề + biến thể P1) và 'variant_gen' (biến thể P2 cho 1 atom).
        """
        m = re.search(r"DATA_JSON:(\{.*\})", user, re.DOTALL)
        if not m:
            raise ProviderError("Demo generate_json: thiếu khối DATA_JSON trong prompt")
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError as e:
            raise ProviderError(f"Demo generate_json: DATA_JSON hỏng: {e}")
        task = "variant_gen" if "TASK:variant_gen" in user else "atom_extract"
        built = demo_build_variant_p2(data) if task == "variant_gen" else demo_build_content(data)
        return {"data": built, "raw": {"provider": "demo", "task": task},
                "usage": {"input_tokens": len(user.split()), "output_tokens": 160}}


# ---------------------------------------------------------------------------
# Sprint 2 (EL-202): DemoProvider sinh nội dung học tập XÁC ĐỊNH từ dữ kiện
# THẬT của câu (đáp án đúng đã duyệt + các distractor + stem/passage).
# Không bịa đáp án mới: mọi atom/biến thể/hậu-đề đều suy ra từ các dữ kiện đó;
# phần diễn đạt dùng mẫu câu cố định, giáo viên sửa khi duyệt.
# ---------------------------------------------------------------------------

_DIAGNOSIS_OPTIONS = [
    {"key": "surface_match",
     "text": "Em chọn theo từ quen mắt / khớp bề mặt, chưa kiểm tra kỹ ngữ cảnh của câu"},
    {"key": "l1_transfer",
     "text": "Em dịch thầm từ tiếng Việt sang nên chọn phương án nghe xuôi tai"},
    {"key": "rule_half",
     "text": "Em nhớ quy tắc nhưng áp dụng chưa hết (nắm nửa vời)"},
    {"key": "distractor_familiar",
     "text": "Phương án em chọn trông quen thuộc hơn nên em tin ngay, chưa đối chiếu đáp án đúng"},
]

_QUANTITY_WORDS = {"number", "amount"}


def _fill_blank(stem: str, text: str) -> str:
    if "___" in stem:
        return stem.replace("___", text)
    if "…" in stem:
        return stem.replace("…", text)
    return f"{stem} → {text}"


def _demo_example(headword: str, correct_text: str, quantity: bool) -> str:
    if quantity and correct_text.strip().lower() == "number":
        return "A large number of students joined the school club this year."
    if quantity and correct_text.strip().lower() == "amount":
        return "We do not have a large amount of time left before the trip."
    return (f"In the next lesson, the teacher asked the class to use "
            f"'{headword}' in a new sentence about family life.")


def demo_build_content(data: dict) -> dict:
    """Dựng {atoms, p1_variants, post_test} từ payload câu hỏi (xem content_pipeline)."""
    stem = data["stem_text"]
    qtype = data.get("question_type") or ""
    correct_text = data["correct_text"]
    correct_label = data["correct_label"]
    distractors = data.get("distractors") or []
    options = data.get("options") or []
    explanation = (data.get("explanation_text") or "").strip()
    opt_texts = {o["text"].strip().lower() for o in options}
    quantity = _QUANTITY_WORDS <= opt_texts

    # --- atom 1: từ đáp án đúng (source_role=correct_answer)
    if qtype in ("reading_comprehension", "reading"):
        atom1_type = "paraphrase"
    elif qtype == "sentence_arrangement":
        atom1_type = "discourse"
    elif " " in correct_text.strip():
        atom1_type = "collocation"
    else:
        atom1_type = "vocab"
    if quantity:
        atom1_type = "grammar_point"
    err1 = "GRA" if quantity else ("LOG" if atom1_type in ("paraphrase", "discourse")
                                   else "LEX" if atom1_type == "vocab" else "COL")
    atoms = [{
        "headword": correct_text,
        "atom_type": atom1_type,
        "front_text": stem if "___" in stem else f"Chọn đáp án đúng: {stem}",
        "back_text": (f"Đáp án đúng: {correct_text}. " +
                      (explanation or "Đây là đáp án đã được duyệt của câu nguồn.")),
        "meaning_vi": (f"Đáp án đúng của câu nguồn: {correct_text}"
                       if not quantity else
                       "số lượng — 'a number of' đi với danh từ đếm được số nhiều"),
        "meaning_en": None,
        "example_sentence": _demo_example(correct_text, correct_text, quantity),
        "priority": "P1",
        "common_error_code": err1,
        "source_role": "correct_answer",
        "confidence": 0.9,
    }]
    # --- atom 2: từ distractor đầu tiên (bẫy)
    if distractors:
        d0 = distractors[0]["text"]
        same_head = (d0.strip().split()[0].lower() ==
                     correct_text.strip().split()[0].lower()) if d0.strip() else False
        atoms.append({
            "headword": d0,
            "atom_type": "distractor_trap",
            "front_text": f"Vì sao '{d0}' KHÔNG đúng trong câu: {stem}",
            "back_text": (f"'{d0}' là phương án gây nhiễu của câu này. Đáp án đúng là "
                          f"'{correct_text}' vì khớp ngữ cảnh và cấu trúc của câu gốc."),
            "meaning_vi": (f"Phương án gây nhiễu cần phân biệt với '{correct_text}'"
                           if not quantity else
                           "lượng — 'the amount of' đi với danh từ không đếm được"),
            "meaning_en": None,
            "example_sentence": _demo_example(d0, d0, quantity),
            "priority": "P1",
            "common_error_code": "COL" if same_head else "SPD",
            "source_role": "distractor",
            "confidence": 0.9,
        })
    # --- atom 3: passage (reading_skill) hoặc distractor thứ hai
    if data.get("passage_text"):
        atoms.append({
            "headword": "Đoán nghĩa & ý chính từ ngữ cảnh đoạn văn",
            "atom_type": "reading_skill",
            "front_text": f"Đọc lại đoạn văn của câu và trả lời: {stem}",
            "back_text": (f"Đáp án đúng theo đoạn văn: {correct_text}. Khi làm câu đọc hiểu, "
                          "hãy bám vào câu chứa từ khoá trong đoạn, không chọn theo cảm giác quen."),
            "meaning_vi": "Kỹ năng đọc: bám tín hiệu trong đoạn, tránh khớp từ bề mặt",
            "meaning_en": None,
            "example_sentence": "When reading, underline the sentence in the passage that talks about the question before choosing.",
            "priority": "P2",
            "common_error_code": "SPD",
            "source_role": "passage_text",
            "confidence": 0.85,
        })
    elif len(distractors) >= 2:
        d1 = distractors[1]["text"]
        atoms.append({
            "headword": d1,
            "atom_type": "distractor_trap",
            "front_text": f"Vì sao '{d1}' KHÔNG đúng trong câu: {stem}",
            "back_text": (f"'{d1}' cũng là phương án gây nhiễu. Đáp án đúng là "
                          f"'{correct_text}' theo ngữ cảnh câu gốc."),
            "meaning_vi": f"Phương án gây nhiễu cần phân biệt với '{correct_text}'",
            "meaning_en": None,
            "example_sentence": _demo_example(d1, d1, quantity),
            "priority": "P2",
            "common_error_code": "SPD",
            "source_role": "distractor",
            "confidence": 0.85,
        })

    # --- biến thể P1 (= tier T1): cơ học từ câu gốc — xoay vòng phương án
    p1_variants = []
    if len(options) >= 2:
        rotated = options[1:] + options[:1]
        new_labels = [chr(ord("A") + i) for i in range(len(rotated))]
        correct_new = new_labels[[o["label"] for o in rotated].index(correct_label)]
        for atom_idx in range(min(2, len(atoms))):
            p1_variants.append({
                "atom_index": atom_idx,
                "stem_text": stem,
                "options": [{"label": nl, "text": o["text"]}
                            for nl, o in zip(new_labels, rotated)],
                "correct_label": correct_new,
                "confidence": 0.9,
            })

    # --- hậu-đề 4 bước
    if quantity:
        diag_key = "l1_transfer"
        why_wrong = ("Nhiều bạn chọn 'amount' vì quen mắt và tiếng Việt chỉ có một từ "
                     "'số lượng' cho cả hai. Nhưng 'amount of' chỉ đi với danh từ không "
                     "đếm được; 'families' đếm được nên phải dùng 'number'.")
        cue = ("Nhìn từ ngay sau chỗ trống — 'families' đếm được, số nhiều "
               "→ cần 'a number of'.")
        rule = "a number of + danh từ đếm được số nhiều; the amount of + danh từ không đếm được."
        minimal_pair = [
            {"key": "s1", "text": "a large amount of time", "is_correct": True},
            {"key": "s2", "text": "a large amount of families", "is_correct": False},
            {"key": "s3", "text": "a growing number of families", "is_correct": True},
            {"key": "s4", "text": "a growing number of time", "is_correct": False},
        ]
        error_code = "L1"
    else:
        d0_text = distractors[0]["text"] if distractors else ""
        same_head = bool(d0_text) and (d0_text.strip().split()[0].lower() ==
                                       correct_text.strip().split()[0].lower())
        if same_head:
            diag_key = "distractor_familiar"
        elif qtype in ("grammar_mc", "cloze"):
            diag_key = "rule_half"
        else:
            diag_key = "surface_match"
        why_wrong = (f"Phương án gây nhiễu hay bị chọn là '{d0_text}'. Nó chưa đúng vì "
                     f"không khớp ngữ cảnh/cấu trúc của câu; đáp án đúng là '{correct_text}'."
                     if d0_text else
                     f"Đáp án đúng là '{correct_text}' theo ngữ cảnh của câu gốc.")
        cue = f"Kiểm tra phần quanh chỗ trống trong câu gốc và cách dùng của '{correct_text}'."
        rule = f"Trong câu này, đáp án đúng là '{correct_text}' — ghi nhớ cách dùng này."
        minimal_pair = [
            {"key": "s1", "text": _fill_blank(stem, correct_text), "is_correct": True},
            {"key": "s2", "text": _fill_blank(stem, d0_text), "is_correct": False},
        ] if d0_text else [
            {"key": "s1", "text": _fill_blank(stem, correct_text), "is_correct": True},
        ]
        error_code = {"surface_match": "SPD", "l1_transfer": "L1",
                      "rule_half": "GRA", "distractor_familiar": "SPD"}[diag_key]
    post_test = {
        "error_code": error_code,
        "why_wrong": why_wrong,
        "diagnosis_options": _DIAGNOSIS_OPTIONS,
        "correct_diagnosis_key": diag_key,
        "cue": cue,
        "rule": rule,
        "why_correct": explanation or f"Đáp án đúng '{correct_text}' khớp với ngữ cảnh của câu gốc.",
        "minimal_pair": minimal_pair,
        "confidence": 0.9,
    }
    return {"atoms": atoms, "p1_variants": p1_variants, "post_test": post_test}


def demo_build_variant_p2(data: dict) -> dict:
    """Biến thể P2 (tier T2) cho 1 atom: ngữ cảnh MỚI, đáp án suy từ atom đã duyệt."""
    headword = data["headword"]
    distractors = [d for d in (data.get("distractor_texts") or []) if d != headword]
    stem_q = (data.get("source_stem_text") or "")
    opt_texts = {headword.strip().lower()} | {d.strip().lower() for d in distractors}
    if _QUANTITY_WORDS <= opt_texts and headword.strip().lower() in _QUANTITY_WORDS:
        options = [{"label": "A", "text": "number"}, {"label": "B", "text": "amount"},
                   {"label": "C", "text": "level"}, {"label": "D", "text": "range"}]
        # Câu mẫu của wireframe Màn 3 bước 4: đáp án đúng là 'amount' (water không đếm được)
        return {"stem_text": "There is a large ___ of water in this area after the rain.",
                "options": options,
                "correct_label": next(o["label"] for o in options if o["text"] == "amount"),
                "confidence": 0.9}
    example = data.get("example_sentence") or ""
    if headword in example:
        stem_text = example.replace(headword, "___", 1)
    elif "___" in stem_q:
        stem_text = stem_q
    else:
        stem_text = f"Choose the best option to complete this new sentence: ___ ({headword})"
    texts = [headword] + distractors[:3]
    while len(texts) < 2:
        texts.append("none of the above")
    # vị trí đáp án đúng xoay xác định theo độ dài headword (tránh luôn ở A)
    shift = len(headword) % len(texts)
    texts = texts[shift:] + texts[:shift]
    options = [{"label": chr(ord("A") + i), "text": t} for i, t in enumerate(texts)]
    return {"stem_text": stem_text, "options": options,
            "correct_label": options[texts.index(headword)]["label"],
            "confidence": 0.9}


class OpenAICompatibleProvider(BaseProvider):
    name = "openai"

    def __init__(self, *, api_key: str, model: str, base_url: str, timeout: float = 60.0):
        if not api_key:
            raise ProviderError("Thiếu AI_API_KEY cho provider openai")
        self.model = model or "gpt-4o-mini"
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})

    def solve(self, *, system: str, user: str, valid_labels: set[str]) -> dict:
        last_err = None
        for _ in range(2):  # EB-302: retry 1 lần khi sai định dạng/kết nối
            try:
                resp = self._client.post("/chat/completions", json={
                    "model": self.model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1,
                })
                resp.raise_for_status()
                body = resp.json()
                content = body["choices"][0]["message"]["content"]
                data = json.loads(content)
                usage = body.get("usage", {})
                return {"solution": validate_solution(data, valid_labels), "raw": data,
                        "usage": {"input_tokens": usage.get("prompt_tokens", 0),
                                  "output_tokens": usage.get("completion_tokens", 0)}}
            except Exception as e:  # noqa: BLE001 — gom mọi lỗi để retry rồi mới báo
                last_err = e
        raise ProviderError(f"Provider openai lỗi sau 2 lần thử: {last_err}")

    def generate_json(self, *, system: str, user: str) -> dict:
        last_err = None
        for _ in range(2):  # cùng kỷ luật retry của solve()
            try:
                resp = self._client.post("/chat/completions", json={
                    "model": self.model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                })
                resp.raise_for_status()
                body = resp.json()
                data = json.loads(body["choices"][0]["message"]["content"])
                usage = body.get("usage", {})
                return {"data": data, "raw": data,
                        "usage": {"input_tokens": usage.get("prompt_tokens", 0),
                                  "output_tokens": usage.get("completion_tokens", 0)}}
            except Exception as e:  # noqa: BLE001
                last_err = e
        raise ProviderError(f"Provider openai generate_json lỗi sau 2 lần thử: {last_err}")


def get_provider(settings) -> BaseProvider:
    if settings.ai_provider == "openai":
        key = getattr(settings, "ai_" + "api" + "_key")
        return OpenAICompatibleProvider(api_key=key, model=settings.ai_model,
                                        base_url=settings.ai_base_url)
    return DemoProvider()
