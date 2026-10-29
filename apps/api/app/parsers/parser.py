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


def _is_bold(el) -> bool:
    if el.name in ("b", "strong"):
        return True
    m = re.search(r"font-weight:\s*([^;]+)", _style(el))
    if not m:
        return False
    v = m.group(1).strip()
    return v in ("bold", "bolder") or (v.isdigit() and int(v) >= 600)


def _is_underline(el) -> bool:
    if el.name == "u":
        return True
    return "underline" in (_style(el) or "")


def _is_italic(el) -> bool:
    return el.name in ("i", "em") or "italic" in (_style(el) or "")


def _markers_to_html(s: str) -> str:
    """Khôi phục định dạng nhấn mạnh từ marker nội bộ: [[B]]-><b>, [[U]]-><u>.
    Marker đáp án [[A]] bị gỡ (đáp án được thể hiện qua correct_option_id, không tô lại)."""
    s = re.sub(r"\[\[A\]\](.*?)\[\[/A:\w+\]\]", r"\1", s)
    return (s.replace("[[B]]", "<b>").replace("[[/B]]", "</b>")
             .replace("[[U]]", "<u>").replace("[[/U]]", "</u>")
             .replace("[[I]]", "<i>").replace("[[/I]]", "</i>"))


def _markers_to_text(s: str) -> str:
    return re.sub(r"\[\[A\]\]|\[\[/A:\w+\]\]|\[\[B\]\]|\[\[/B\]\]|\[\[U\]\]|\[\[/U\]\]|\[\[I\]\]|\[\[/I\]\]", "", s)


def _mark_answers(soup) -> None:
    """Bọc text ở lá DOM bằng marker nội bộ:
    [[A]]..[[/A:source]] = tín hiệu đáp án (đỏ/highlight);
    [[B]]..[[/B]] = in đậm, [[U]]..[[/U]] = gạch chân — ĐÂY LÀ NỘI DUNG ĐỀ (từ/câu cần
    học sinh nhận biết), phải được khôi phục thành <b>/<u> khi lưu stem_html/passage,
    TUYỆT ĐỐI không để lọt marker thô vào dữ liệu lưu trữ."""
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
        elif _is_underline(el):
            el.string = f"[[U]]{text}[[/U]]"
        elif _is_italic(el):
            el.string = f"[[I]]{text}[[/I]]"
        elif _is_bold(el):
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
                "number": num, "stem": _markers_to_text(body.strip()),
                "stem_html": _markers_to_html(body.strip()), "options": [],
                "detected_answer": None,
                "warnings": ["Không tách được phương án A-D"],
                "question_type": _guess_type(_markers_to_text(body), bool(passage_chunks)),
            })
            continue
        stem_raw = body[: marks[0].start()].strip()
        stem = _markers_to_text(stem_raw)
        options, detected = [], None
        for i, mk in enumerate(marks):
            start = mk.end()
            end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
            seg = body[start:end].strip()
            dm = re.search(r"\[\[A\]\](.*?)\[\[/A:(\w+)\]\]", seg)
            emph_len = sum(len(x) for x in re.findall(r"\[\[(?:B|U)\]\](.*?)\[\[/(?:B|U)\]\]", seg))
            clean_seg = _markers_to_text(seg).strip()
            if dm and detected is None:
                detected = {"label": mk.group(1), "source": dm.group(2),
                            "confidence": 0.99 if dm.group(2) == "red_text" else 0.97}
            options.append({"label": mk.group(1), "text": clean_seg,
                            "html": _markers_to_html(seg).strip(),
                            "_bold_ratio": (emph_len / len(clean_seg)) if clean_seg else 0})
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
            "number": num, "stem": stem, "stem_html": _markers_to_html(stem_raw), "options": options,
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
        joined = " ".join(passage_chunks)
        passages.append({
            "temp_id": "p1", "passage_type": "reading_comprehension",
            "content_text": _markers_to_text(joined),
            "content_html": _markers_to_html(joined),
            "question_numbers": [q["number"] for q in questions],
        })
        for q in questions:
            q["passage_temp_id"] = "p1"
    return {"passages": passages, "questions": questions}
