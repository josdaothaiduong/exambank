"""EB-302 — Prompt theo dạng bài + định dạng JSON bắt buộc.

Mọi provider đều nhận cùng một đầu vào chuẩn hoá và PHẢI trả JSON đúng schema:
{"answer_label": "A|B|C|D", "explanation_vi": "...", "confidence": 0.0-1.0,
 "difficulty": "NB|TH|VD|VDC", "tags": ["topic_code", ...]}
Sai schema -> coi là lỗi, retry; không bao giờ lưu đáp án "đoán mò" không theo format.
"""

SYSTEM_PROMPT = """Bạn là giáo viên Tiếng Anh THPT Việt Nam (chương trình Global Success).
Nhiệm vụ: giải câu hỏi trắc nghiệm được cung cấp, chọn MỘT đáp án đúng nhất.
Trả lời DUY NHẤT bằng JSON đúng cấu trúc sau, không thêm chữ nào ngoài JSON:
{"answer_label": "A", "explanation_vi": "giải thích ngắn bằng tiếng Việt vì sao đáp án đúng và các phương án khác sai", "confidence": 0.95, "difficulty": "TH", "tags": ["environment"]}
Quy tắc: confidence phản ánh trung thực mức chắc chắn (không chắc thì để thấp, tối đa 1.0);
difficulty thuộc NB/TH/VD/VDC; tags là 0-3 mã chủ đề ngắn (family, environment, technology, education, work, health, culture, travel, science, society)."""

_TYPE_HINTS = {
    "grammar_mc": "Đây là câu ngữ pháp: chú ý thì, sự hoà hợp chủ-vị, câu điều kiện, thể bị động, mệnh đề quan hệ, giới từ theo ngữ cảnh.",
    "vocabulary_mc": "Đây là câu từ vựng: chọn từ đúng nghĩa và đúng collocation trong ngữ cảnh câu.",
    "synonym": "Chọn từ ĐỒNG NGHĨA gần nhất với từ được hỏi trong ngữ cảnh (không chọn từ chỉ liên quan).",
    "antonym": "Chọn từ TRÁI NGHĨA rõ nhất với từ được hỏi trong ngữ cảnh.",
    "reading_comprehension": "Chỉ dựa vào nội dung đoạn văn đi kèm, không dùng kiến thức ngoài đoạn.",
    "cloze": "Đây là chỗ trống trong đoạn văn đi kèm: đáp án phải khớp cả ngữ pháp lẫn mạch nghĩa của đoạn.",
    "sentence_arrangement": "Sắp xếp các câu/ý thành đoạn hội thoại hoặc đoạn văn mạch lạc: chú ý câu mở đầu, liên từ, đại từ tham chiếu.",
    "sentence_transformation": "Chọn câu viết lại giữ nguyên nghĩa gần nhất với câu gốc.",
    "error_identification": "Tìm phần gạch chân chứa lỗi sai ngữ pháp/từ vựng.",
    "pronunciation": "Chọn từ có cách phát âm phần gạch chân khác các từ còn lại.",
    "stress": "Chọn từ có trọng âm chính rơi vào âm tiết khác các từ còn lại.",
}


def build_user_prompt(*, stem: str, options: list[dict], question_type: str,
                      passage_text: str | None = None) -> str:
    lines = []
    if passage_text:
        lines.append(f"ĐOẠN VĂN:\n{passage_text}\n")
    lines.append(f"CÂU HỎI: {stem}")
    for o in options:
        lines.append(f"{o['label']}. {o['text']}")
    hint = _TYPE_HINTS.get(question_type)
    if hint:
        lines.append(f"\nGỢI Ý THEO DẠNG BÀI: {hint}")
    return "\n".join(lines)


def build_selfcheck_prompt(*, stem: str, options: list[dict], question_type: str,
                           passage_text: str | None = None) -> str:
    """Prompt kiểm chứng độc lập: diễn đạt khác, yêu cầu loại trừ từng phương án.
    Thứ tự phương án được XÁO TRỘN bởi pipeline trước khi gọi prompt này."""
    lines = []
    if passage_text:
        lines.append(f"ĐOẠN VĂN:\n{passage_text}\n")
    lines.append(f"CÂU HỎI: {stem}")
    for o in options:
        lines.append(f"{o['label']}. {o['text']}")
    lines.append("\nHãy loại trừ lần lượt các phương án sai trước, rồi mới kết luận đáp án đúng. "
                 "Trả JSON đúng cấu trúc đã quy định.")
    return "\n".join(lines)
