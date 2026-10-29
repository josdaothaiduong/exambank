"""EB-202 + EB-203 — Parser server + Answer Detector.

Port từ prototype Bước 2 (JS), sau đó nâng cấp theo dữ liệu 5 đề thật (2026-10-29):
- Header câu chấp nhận cả "Question 1:" lẫn "Question 1." (đề THPT thật dùng dấu chấm).
- Run bị Word cắt nhỏ ("B" + "." + text) -> chuẩn hoá marker "B ." thành "B.".
- Màu đỏ nhận theo dải đỏ thật (FF0000, EE0000, C00000...) nhưng LOẠI hồng trang trí
  kiểu E8336D (một đề thật tô hồng mọi chữ cái phương án — đó là trang trí, không phải đáp án).
- Đáp án có thể chỉ được tô ở CHỮ CÁI phương án: chỉ tin khi đúng 1 phương án có dấu.
- Nhiều passage theo từng section (đề THPT có 4-6 section), không gộp thành 1 passage.
- Câu cloze không có stem (chỗ trống nằm trong đoạn) -> stem mô tả rõ ràng.

Đầu ra tuân thủ Parser Contract (Bước 1, mục 6.1). Parser không chắc đáp án ->
detected_answer = None, TUYỆT ĐỐI không đoán bừa.
"""
import re

from bs4 import BeautifulSoup

from app.parsers.sanitize import sanitize_html

# Word cắt run rất vụn ("Question 1" + "7", "Question" | "7:") và marker nội bộ chen giữa
# các token cấu trúc -> mọi regex cấu trúc phải chấp nhận marker/khoảng trắng chen giữa (GAP).
_MARK = r"\[\[/?(?:A|B|U|I)(?::\w+)?\]\]"
_GAP = rf"(?:\s|{_MARK})*"
_NUM = rf"\d+(?:{_GAP}\d+)*"
_QUESTION_SPLIT = re.compile(rf"(?=(?:Question|Câu){_GAP}{_NUM}{_GAP}[:\.])", re.I)
_QUESTION_HEAD = re.compile(rf"^(?:Question|Câu){_GAP}({_NUM}){_GAP}[:\.]\s*", re.I)
# Phần đuôi dùng lookahead (?=\s|$) — KHÔNG tiêu thụ khoảng trắng, nếu không dấu cách đó
# vừa là đuôi của phương án trước vừa là đầu của phương án sau sẽ làm mất 1 phương án.
_OPTION_MARKS = re.compile(rf"(?:^|\s|\]\])([A-D]){_GAP}\.(?=\s|$)")
_ANSWER_KEY_HEAD = re.compile(r"(ĐÁP\s*ÁN|ANSWER\s*KEY)\s*:?", re.I)
_ANSWER_KEY_PAIR = re.compile(r"(\d+)\s*[\.\)\-:]\s*([A-D])\b|(\d+)\s*([A-D])\b")
_LABEL_ONLY = re.compile(r"^[A-D]\.?$")
_INSTR_START = re.compile(
    r"^(read|choose|mark|listen|look|exercise|part|section|questions?)\b", re.I)


def _style(el) -> str:
    return (el.get("style") or "").lower() if hasattr(el, "get") else ""


def _is_red(el) -> bool:
    """Đỏ thật: kênh R cao, G thấp, B đủ thấp để loại hồng/magenta trang trí (E8336D có B=109)."""
    m = re.search(r"color:\s*([^;]+)", _style(el))
    if not m:
        return False
    v = m.group(1).strip()
    if v == "red":
        return True
    rgb = None
    hm = re.fullmatch(r"#([0-9a-f]{6})", v)
    if hm:
        h = hm.group(1)
        rgb = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    else:
        rm = re.fullmatch(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", v)
        if rm:
            rgb = tuple(int(x) for x in rm.groups())
    if rgb is None:
        return False
    r, g, b = rgb
    return r >= 180 and g <= 100 and b <= 90 and (r - g) >= 100


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
    """Khôi phục định dạng nhấn mạnh từ marker nội bộ: [[B]]-><b>, [[U]]-><u>, [[I]]-><i>.
    Marker đáp án [[A]] bị gỡ (đáp án thể hiện qua correct_option_id, không tô lại)."""
    s = re.sub(r"\[\[A\]\](.*?)\[\[/A:\w+\]\]", r"\1", s)
    s = re.sub(r"\[\[/?[A-Z](?::\w+)?\]\]", "", re.sub(r"\[\[A\]\]|\[\[/A:\w+\]\]", "", s)) if "[[A" in s else s
    return (s.replace("[[B]]", "<b>").replace("[[/B]]", "</b>")
             .replace("[[U]]", "<u>").replace("[[/U]]", "</u>")
             .replace("[[I]]", "<i>").replace("[[/I]]", "</i>"))


def _markers_to_text(s: str) -> str:
    s = re.sub(r"\[\[A\]\]|\[\[/A:\w+\]\]|\[\[B\]\]|\[\[/B\]\]|\[\[U\]\]|\[\[/U\]\]|\[\[I\]\]|\[\[/I\]\]", "", s)
    return re.sub(r"\[\[/?[A-Z](?::\w+)?\]?\]?", "", s)  # mảnh marker vỡ còn sót


def _mark_answers(soup) -> None:
    """Bọc text ở lá DOM bằng marker nội bộ:
    [[A]]..[[/A:source]] = tín hiệu đáp án (đỏ/highlight);
    [[B]]/[[U]]/[[I]] = in đậm/gạch chân/nghiêng — ĐÂY LÀ NỘI DUNG ĐỀ (từ/câu cần học sinh
    nhận biết), phải khôi phục thành thẻ khi lưu stem_html/passage, không để lọt marker thô."""
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
    """Tách phần bảng đáp án ở cuối đề (nếu có). Trả ({số câu: label}, text_đã_bỏ_bảng).

    Điều kiện chặt (rút kinh nghiệm từ đề thật K12 Unit 10): trong thân đề có câu văn
    chứa chữ "key" ("...is the key to unlocking...") — nếu bắt mọi chữ "KEY" làm header
    thì phần sau bị cắt sạch. Chỉ nhận header khi nó nằm SAU đầu câu hỏi cuối cùng."""
    last_q = None
    for qm in _QUESTION_SPLIT.finditer(text):
        last_q = qm.start()
    m = None
    for cand in _ANSWER_KEY_HEAD.finditer(text):
        if last_q is None or cand.start() > last_q:
            m = cand
            break
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


def _strip_instructions(chunk: str) -> str:
    """Cắt các câu chỉ dẫn/tiêu đề section ở đầu khối passage ("Read the following...",
    "Exercise 1: Mark the letter...", "Questions 13-17...") — lặp tối đa 3 câu."""
    chunk = re.sub(r"^(\[\[(?:B|U|I)\]\]\s*)+", "", chunk)
    for _ in range(3):
        if not _INSTR_START.match(chunk):
            break
        m = re.search(r"\.\s+", chunk)
        if not m:
            return ""
        rest = chunk[m.end():].strip()
        if len(rest) <= 40:
            return ""
        chunk = rest
    return chunk


def _detect_from_markers(options_raw) -> dict | None:
    """Quyết định đáp án từ các marker [[A]] trong từng phương án.

    options_raw: list dict có 'text_markers' [(content, source)] và 'label_markers'.
    Ưu tiên dấu ở NỘI DUNG phương án; dấu chỉ ở chữ cái chỉ tin khi duy nhất 1 phương án có.
    Nhiều phương án cùng có dấu nội dung -> mơ hồ -> None (không đoán)."""
    with_text = [o for o in options_raw if o["text_markers"]]
    if len(with_text) == 1:
        _, source = with_text[0]["text_markers"][0]
        conf = 0.99 if source == "red_text" else 0.97
        return {"label": with_text[0]["label"], "source": source, "confidence": conf}
    if len(with_text) > 1:
        return None
    with_label = [o for o in options_raw if o["label_markers"]]
    if len(with_label) == 1:
        _, source = with_label[0]["label_markers"][0]
        conf = 0.99 if source == "red_text" else 0.97
        return {"label": with_label[0]["label"], "source": source, "confidence": round(conf * 0.92, 2)}
    return None


def parse_exam_html(html: str) -> dict:
    clean = sanitize_html(html)
    soup = BeautifulSoup(clean, "html.parser")
    _mark_answers(soup)
    raw = soup.get_text(" ").replace("\xa0", " ")
    raw = re.sub(r"[ \t]+", " ", raw).strip()
    # Word cắt run nhỏ + giáo viên hay in đậm/tô màu cả NHÃN phương án và header câu:
    # gỡ marker khỏi các vị trí cấu trúc này để regex tách câu/phương án nhìn thấy dạng sạch.
    # 0) Cả phương án nằm trong 1 run tô màu: "[[A]]C. lifelong learners[[/A]]"
    #    -> đưa nhãn ra ngoài, marker ôm phần nội dung: "C. [[A]]lifelong learners[[/A]]"
    raw = re.sub(r"\[\[A\]\]([A-D])\.\s+", r"\1. [[A]]", raw)
    # 1) Nhãn bị tô đỏ/highlight: "[[A]]C.[[/A]]" -> "C. [[A]]C[[/A]]" (giữ 1 echo marker trong segment để detector biết)
    raw = re.sub(r"\[\[A\]\]([A-D])\.?\s*\[\[/A:(\w+)\]\]\s*\}?", r"\1. [[A]]\1[[/A:\2]]", raw)
    raw = re.sub(r"\[\[A\]\]([A-D])\.?\s*\[\[/A:(\w+)\]\]\s*\.", r"\1. [[A]]\1[[/A:\2]]", raw)
    # 2) Nhãn in đậm/gạch chân/nghiêng (thường là trang trí đồng đều): "[[B]]A.[[/B]]" / "[[B]]A[[/B]] ." -> "A."
    raw = re.sub(r"\[\[(?:B|U|I)\]\]([A-D])\.?\s*\[\[/(?:B|U|I)\]\]\s*\}?", r"\1. ", raw)
    raw = re.sub(r"\[\[(?:B|U|I)\]\]([A-D])\.?\s*\[\[/(?:B|U|I)\]\]\s*\.", r"\1. ", raw)
    # 3) Header câu bị bọc marker: "[[B]]Question 2.[[/B]]" -> "Question 2."
    raw = re.sub(r"\[\[(?:B|U|I)\]\]((?:Question|Câu)\s*\d+\s*[:\.])\[\[/(?:B|U|I)\]\]", r"\1", raw)
    raw = re.sub(r"\[\[(?:B|U|I)\]\]((?:Question|Câu)\s*\d+\s*[:\.])", r"\1", raw)
    # 4) Dấu chấm bị cắt rời khỏi chữ cái (kể cả khi "." là 1 run highlight riêng):
    #    "B ." / "B [[/B]] ." / "[[A]]B[[/A]] [[A]]. [[/A]]" -> gom "." về ngay sau chữ cái.
    raw = re.sub(rf"([A-D])((?:\s|{_MARK})+)\.", r"\1.\2", raw)

    answer_key, raw = _extract_answer_key(raw)

    parts = _QUESTION_SPLIT.split(raw)
    passages, questions = [], []
    pending_chunks: list[str] = []   # text chưa thuộc passage nào (nằm trước câu hỏi tiếp theo)
    current_passage_id: str | None = None

    def flush_passage():
        nonlocal current_passage_id
        chunks = [c for c in (_strip_instructions(c) for c in pending_chunks) if c]
        pending_chunks.clear()
        if chunks:
            joined = " ".join(chunks)
            pid = f"p{len(passages) + 1}"
            passages.append({
                "temp_id": pid, "passage_type": "reading_comprehension",
                "content_text": _markers_to_text(joined),
                "content_html": _markers_to_html(joined),
                "question_numbers": [],
            })
            current_passage_id = pid
        return current_passage_id

    for part in parts:
        part = part.strip()
        if not part:
            continue
        part = re.sub(r"^(\[\[(?:B|U|I)\]\])+", "", part)
        head = _QUESTION_HEAD.match(part)
        if not head:
            if len(part) > 40:
                pending_chunks.append(part)
            continue
        num = int(re.sub(r"\D", "", head.group(1)))
        pid = flush_passage()
        body = re.sub(r"^(\[\[/(?:B|U|I)\]\]\s*)+", "", part[head.end():])
        sec = re.search(rf"(?:Exercise|PART){_GAP}[IVX\d]+{_GAP}[:\.]", body)
        if sec and sec.start() > 0:
            pending_chunks.append(body[sec.start():])
            body = body[: sec.start()]
        marks = list(_OPTION_MARKS.finditer(body))
        if len(marks) < 2:
            questions.append({
                "number": num, "stem": _markers_to_text(body.strip()),
                "stem_html": _markers_to_html(body.strip()), "options": [],
                "detected_answer": None,
                "warnings": ["Không tách được phương án A-D"],
                "question_type": _guess_type(_markers_to_text(body), bool(pid)),
                **({"passage_temp_id": pid} if pid else {}),
            })
            if pid:
                passages[-1]["question_numbers"].append(num)
            continue
        # Section mới thường bắt đầu ngay sau phương án cuối của câu cuối section trước
        # (instruction "Read the following..." + passage) — cắt phần đuôi đó khỏi body,
        # chuyển thành chunk để flush thành passage cho section sau.
        tail_m = re.search(
            r"(?:Read the following|Read the passage|Mark the letter|Exercise\s*\d|PART\s+[IVX\d])",
            body[marks[-1].end():]) if marks else None
        if tail_m:
            cut = marks[-1].end() + tail_m.start()
            pending_chunks.append(body[cut:])
            body = body[:cut]
            marks = list(_OPTION_MARKS.finditer(body))
        if len(marks) > 4:
            win = None
            for k in range(len(marks) - 3):
                if [marks[k + j].group(1) for j in range(4)] == ["A", "B", "C", "D"]:
                    win = k  # lấy cửa sổ cuối cùng thỏa
            if win is not None:
                marks = marks[win:]
        stem_raw = body[: marks[0].start()].strip()
        stem = _markers_to_text(stem_raw)
        if not stem and pid:
            stem = f"Chỗ trống số {num} trong đoạn văn đi kèm"
            stem_raw = stem
        options, raw_opts = [], []
        for i, mk in enumerate(marks):
            start = mk.end()
            end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
            seg = body[start:end].strip()
            echo_label_markers = []
            m_echo = re.match(r"\[\[A\]\]([A-D])\[\[/A:(\w+)\]\]\s*", seg)
            if m_echo and m_echo.group(1) == mk.group(1):
                echo_label_markers.append((m_echo.group(1), m_echo.group(2)))
                seg = seg[m_echo.end():]
            markers = re.findall(r"\[\[A\]\](.*?)\[\[/A:(\w+)\]\]", seg)
            text_markers = [(c, s) for c, s in markers
                            if not _LABEL_ONLY.match(c.strip()) and re.search(r"[A-Za-z0-9]", c)]
            label_markers = [(c, s) for c, s in markers if _LABEL_ONLY.match(c.strip())] + echo_label_markers
            emph_len = sum(len(x) for x in re.findall(r"\[\[(?:B|U)\]\](.*?)\[\[/(?:B|U)\]\]", seg))
            u_len = sum(len(x) for x in re.findall(r"\[\[U\]\](.*?)\[\[/U\]\]", seg))
            clean_seg = _markers_to_text(seg).strip()
            options.append({"label": mk.group(1), "text": clean_seg,
                            "html": _markers_to_html(seg).strip()})
            raw_opts.append({"label": mk.group(1), "text_markers": text_markers,
                             "label_markers": label_markers,
                             "_emph_ratio": (emph_len / len(clean_seg)) if clean_seg else 0,
                             "_u_ratio": (u_len / len(clean_seg)) if clean_seg else 0})
        detected = _detect_from_markers(raw_opts)
        warnings = []
        if detected is None and sum(1 for o in raw_opts if o["text_markers"]) > 1:
            warnings.append("Nhiều phương án cùng có dấu hiệu đáp án — cần giáo viên xác nhận")
        # Nguồn bold_underline: đúng 1 phương án được nhấn gần như toàn bộ, các phương án còn lại hầu như không
        if detected is None:
            bold_opts = [o for o in raw_opts if o["_emph_ratio"] >= 0.8]
            others_max = max((o["_emph_ratio"] for o in raw_opts if o not in bold_opts), default=0)
            if len(bold_opts) == 1 and others_max < 0.3:
                # Gạch chân làm dấu đáp án đáng tin hơn in đậm thuần — đề thật cho thấy in đậm
                # bị dùng trang trí tràn lan (UNIT_3: 806 run bold) nên bold-only hạ xuống 0.65
                # (dưới ngưỡng tin cậy 0.70, giáo viên buộc phải kiểm tra lại khi duyệt).
                conf = 0.80 if bold_opts[0]["_u_ratio"] >= 0.5 else 0.65
                detected = {"label": bold_opts[0]["label"], "source": "bold_underline", "confidence": conf}
        # Nguồn bảng đáp án: chỉ dùng khi chưa có dấu hiệu nào trong thân câu
        if detected is None and num in answer_key:
            detected = {"label": answer_key[num], "source": "answer_key_table", "confidence": 0.95}
        questions.append({
            "number": num, "stem": stem, "stem_html": _markers_to_html(stem_raw),
            "options": options, "detected_answer": detected, "warnings": warnings,
            "question_type": _guess_type(stem, bool(pid)),
            **({"passage_temp_id": pid} if pid else {}),
        })
        if pid:
            passages[-1]["question_numbers"].append(num)

    return {"passages": passages, "questions": questions}
