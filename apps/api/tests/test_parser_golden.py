"""EB-202/203/207 — Bộ đề vàng: 5 file fixture, đo tách câu + nhận đáp án theo từng nguồn."""
import pathlib

from app.parsers.parser import parse_exam_html
from app.parsers.sanitize import sanitize_html

GOLDEN = pathlib.Path(__file__).parent / "golden_files"

# file -> (số câu, {số câu: (label, source)}, số passage)
EXPECTED = {
    "exam1_red.html": (4, {1: ("B", "red_text"), 2: ("B", "red_text"), 3: ("B", "red_text"), 4: ("B", "red_text")}, 0),
    "exam2_highlight.html": (3, {1: ("B", "highlight"), 2: ("C", "highlight"), 3: ("B", "highlight")}, 1),
    "exam3_noanswer_key.html": (3, {1: ("A", "answer_key_table"), 2: ("A", "answer_key_table"), 3: ("B", "answer_key_table")}, 0),
    "exam4_cloze.html": (3, {}, 1),
    "exam5_mixed_bold.html": (3, {1: ("B", "bold_underline"), 2: ("A", "bold_underline")}, 0),
    # exam6: định dạng rút từ 5 đề thật Ha gửi 2026-10-29 — header "Question 1." dấu chấm,
    # đỏ biến thể #ee0000, highlight bị cắt run vụn ("B" "." "with"), section mới nối đuôi câu trước
    "exam6_real_formats.html": (3, {1: ("C", "red_text"), 2: ("B", "highlight"), 3: ("B", "red_text")}, 2),
}


def test_golden_files_all():
    total_q, correct_ans = 0, 0
    for fname, (n_q, answers, n_p) in EXPECTED.items():
        out = parse_exam_html((GOLDEN / fname).read_text())
        assert len(out["questions"]) == n_q, f"{fname}: tách {len(out['questions'])} != {n_q} câu"
        assert len(out["passages"]) == n_p, f"{fname}: passage {len(out['passages'])} != {n_p}"
        by_num = {q["number"]: q for q in out["questions"]}
        for num, (label, source) in answers.items():
            det = by_num[num]["detected_answer"]
            assert det is not None, f"{fname} Q{num}: không nhận được đáp án"
            assert det["label"] == label and det["source"] == source, f"{fname} Q{num}: {det}"
            correct_ans += 1
        for num, q in by_num.items():
            if num not in answers:
                assert q["detected_answer"] is None, f"{fname} Q{num}: bịa đáp án {q['detected_answer']}"
        total_q += n_q
    # Chỉ số chất lượng trên bộ vàng: 13 câu, 12 đáp án kỳ vọng — hàm này assert từng câu nên đạt 100% mới pass
    print(f"Golden: {total_q} questions, {correct_ans} expected answers detected exactly")


def test_golden_passage_not_split_from_questions():
    out = parse_exam_html((GOLDEN / "exam2_highlight.html").read_text())
    assert out["passages"][0]["question_numbers"] == [1, 2, 3]
    assert "Green living" in out["passages"][0]["content_text"]
    assert "Read the passage" not in out["passages"][0]["content_text"]


def test_sanitize_removes_script_keeps_answer_signal():
    dirty = '<p onclick="hack()">Q <script>alert(1)</script><span style="color:#ff0000; font-size:99px">red</span></p>'
    clean = sanitize_html(dirty)
    assert "script" not in clean and "onclick" not in clean and "alert" not in clean
    assert "color" in clean and "red" in clean and "font-size" not in clean
