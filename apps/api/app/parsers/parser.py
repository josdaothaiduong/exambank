"""EB-202 + EB-203 — Parser server + Answer Detector.

Port trung thực logic đã kiểm chứng ở prototype Bước 2 (JS) sang Python,
cộng thêm 2 nguồn đáp án mới ở server: bold_underline và answer_key_table.

Đầu ra tuân thủ Parser Contract (Bước 1, mục 6.1):
  { passages: [...], questions: [{stem, options[], detected_answer{label,source,confidence}|None, warnings[]}] }
Parser không chắc đáp án -> detected_answer = None, TUYỆT ĐỐI không đoán bừa.
"""
import re

from bs4 import BeautifulSoup

from app.parsers.sanitize import sanitize_html

_RED = re.compile(r"rgb\(\s*255\s*,\s*0\s*,\s*0\s*\)|#ff0000\b|\bred\b", re.I)
_QUESTION_SPLIT = re.compile(r"(?=Question\s*\d+\s*:|Câu\s*\d+\s*:)", re.I)
_QUESTION_HEAD = re.compile(r"^(?:Question|Câu)\s*(\d+)\s*:\s*", re.I)
_OPTION_MARKS = re.compile(r"(?:^|\s)([A-D])\.\s+")
_ANSWER_KEY_HEAD = re.compile(r"(ĐÁP\s*ÁN|ANSWER\s*KEY|KEY)\s*:?", re.I)
_ANSWER_KEY_PAIR = re.compile(r"(\d+)\s*[\.\)\-:]\s*([A-D])\b|(\d+)\s*([A-D])\b")


def _style(el) -> str:
    return (el.get("style") or "").lower() if hasattr(el, "get") else ""


def _is_red(el) -> bool:
    m = re.search(r"color:\s*([^;]+)", _style(el))
    return bool(m and _RED.search(m.group(1)))


def _is_highlight(el) -> bool:
    m = re.search(r"background-color:\s*([^;]+)", _style(el))
    if not m:
        return False
    v = m.group(1).strip()
    return v not in ("transparent", "#ffffff", "rgb(255, 255, 255)") and not v.startswith("rgba(0, 0, 0")


def _mark_answers(soup) -> None:
    """Bọc text ở lá DOM bằng marker: [[A]]..[[/A:source]] cho đỏ/highlight,
    [[B]]..[[/B]] cho bold/underline (chỉ dùng xét trong phạm vi 1 phương án)."""
    for el in soup.find_all(True):
        if el.find(True) is not None:  # chỉ xét phần tử lá
            continue
        text = el.get_text()
        if not text.strip():
            continue
        if _is_red(el):
            el.string = f"[[A]]{text}[[/A:red_text]]"
        elif _is_highlight(el):
            el.string = f"[[A]]{text}[[/A:highlight]]"
        elif el.name in ("b", "strong", "u"):
            el.string = f"[[B]]{text}[[/B]]"


def _extract_answer_key(text: str):
    """Tách phần bảng đáp án ở cuối đề (nếu có). Trả ({số câu: label}, text_đã_bỏ_bảng)."""
    m = _ANSWER_KEY_HEAD.search(text)
    if not m:
        return {}, text
    head, tail = text[: m.start()], text[m.end():]
    pairs = {}
    for pm in _ANSWER_KEY_PAIR.finditer(tail):
        num = pm.group(1) or pm.group(3)
        label = pm.group(2) or pm.group(4)
        if num and label:
            pairs[int(num)] = label
    # Chỉ coi là bảng đáp án thật khi có ít nhất 2 cặp — tránh nhầm nội dung câu hỏi
    if len(pairs) >= 2:
        return pairs, head
    return {}, text


def _guess_type(stem: str, has_passage: bool) -> str:
    s = stem.lower()
    if "closest in meaning" in s:
        return "synonym"
    if "opposite in meaning" in s:
        return "antonym"
    if has_passage:
        return "reading_comprehension"
    return "grammar_mc"


def parse_exam_html(html: str) -> dict:
    clean = sanitize_html(html)
    soup = BeautifulSoup(clean, "html.parser")
    _mark_answers(soup)
    raw = soup.get_text(" ").replace("\xa0", " ")
    raw = re.sub(r"[ \t]+", " ", raw).strip()

    answer_key, raw = _extract_answer_key(raw)

    parts = _QUESTION_SPLIT.split(raw)
    passage_chunks, questions = [], []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        head = _QUESTION_HEAD.match(part)
        if not head:
            if len(part) > 40:
                passage_chunks.append(part)
            continue
        num = int(head.group(1))
        body = part[head.end():]
        marks = list(_OPTION_MARKS.finditer(body))
        if len(marks) < 2:
            questions.append({
                "number": num, "stem": body.strip(), "options": [],
                "detected_answer": None,
                "warnings": ["Không tách được phương án A-D"],
                "question_type": _guess_type(body, bool(passage_chunks)),
            })
            continue
        stem = body[: marks[0].start()].strip()
        options, detected = [], None
        for i, mk in enumerate(marks):
            start = mk.end()
            end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
            seg = body[start:end].strip()
            dm = re.search(r"\[\[A\]\](.*?)\[\[/A:(\w+)\]\]", seg)
            bold_len = sum(len(x) for x in re.findall(r"\[\[B\]\](.*?)\[\[/B\]\]", seg))
            clean_seg = re.sub(r"\[\[A\]\]|\[\[/A:\w+\]\]|\[\[B\]\]|\[\[/B\]\]", "", seg).strip()
            if dm and detected is None:
                detected = {"label": mk.group(1), "source": dm.group(2),
                            "confidence": 0.99 if dm.group(2) == "red_text" else 0.97}
            options.append({"label": mk.group(1), "text": clean_seg,
                            "_bold_ratio": (bold_len / len(clean_seg)) if clean_seg else 0})
        # Nguồn bold_underline: đúng 1 phương án được in đậm/gạch chân gần như toàn bộ
        if detected is None:
            bold_opts = [o for o in options if o["_bold_ratio"] >= 0.8]
            if len(bold_opts) == 1:
                detected = {"label": bold_opts[0]["label"], "source": "bold_underline", "confidence": 0.80}
        # Nguồn bảng đáp án: chỉ dùng khi chưa có dấu hiệu nào trong thân câu
        if detected is None and num in answer_key:
            detected = {"label": answer_key[num], "source": "answer_key_table", "confidence": 0.95}
        for o in options:
            o.pop("_bold_ratio", None)
        questions.append({
            "number": num, "stem": stem, "options": options,
            "detected_answer": detected, "warnings": [],
            "question_type": _guess_type(stem, bool(passage_chunks)),
        })

    # Cắt câu chỉ dẫn ở đầu passage ("Read the passage and choose... . <passage thật>")
    # vì get_text nối chỉ dẫn + đoạn văn thành 1 khối duy nhất trước Question đầu tiên.
    _INSTR = re.compile(r"^(read|choose|mark|listen|look)\b", re.I)

    def _strip_instruction(chunk: str) -> str:
        if not _INSTR.match(chunk):
            return chunk
        m = re.search(r"\.\s+", chunk)
        if m:
            rest = chunk[m.end():].strip()
            return rest if len(rest) > 40 else ""
        return ""

    passage_chunks = [c for c in (_strip_instruction(c) for c in passage_chunks) if c]
    passages = []
    if passage_chunks and questions:
        passages.append({
            "temp_id": "p1", "passage_type": "reading_comprehension",
            "content_text": " ".join(passage_chunks),
            "question_numbers": [q["number"] for q in questions],
        })
        for q in questions:
            q["passage_temp_id"] = "p1"
    return {"passages": passages, "questions": questions}
