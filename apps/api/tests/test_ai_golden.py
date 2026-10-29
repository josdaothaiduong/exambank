"""EB-307 — Đo chất lượng provider trên 50 câu vàng (đề thật Unit 3, có đáp án chuẩn).

Test này KHÔNG đòi điểm cao với DemoProvider (bộ giải quy tắc offline) — nó đòi harness
chạy trọn vẹn và xuất báo cáo đúng cấu trúc. Khi cắm provider thật (AI_PROVIDER=openai),
chạy lại để lấy tỉ lệ đúng thực tế theo từng dạng bài.
"""
import json
import pathlib
from collections import Counter, defaultdict

from app.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from app.ai.provider import DemoProvider

GOLDEN = json.loads((pathlib.Path(__file__).parent / "ai_golden_50.json").read_text())


def run_eval(provider) -> dict:
    per_type = defaultdict(lambda: {"total": 0, "correct": 0})
    wrong = []
    for item in GOLDEN["items"]:
        opts = [{"label": o["label"], "text": o["text"]} for o in item["options"]]
        res = provider.solve(
            system=SYSTEM_PROMPT,
            user=build_user_prompt(stem=item["stem"], options=opts,
                                   question_type=item["type"], passage_text=item["passage"]),
            valid_labels={o["label"] for o in opts})
        got = res["solution"]["answer_label"]
        per_type[item["type"]]["total"] += 1
        if got == item["answer"]:
            per_type[item["type"]]["correct"] += 1
        else:
            wrong.append({"id": item["id"], "type": item["type"],
                          "expected": item["answer"], "got": got,
                          "confidence": res["solution"]["confidence"]})
    total = sum(v["total"] for v in per_type.values())
    correct = sum(v["correct"] for v in per_type.values())
    return {"provider": provider.model, "total": total, "correct": correct,
            "accuracy": round(correct / total, 3) if total else 0.0,
            "per_type": {k: {**v, "accuracy": round(v["correct"] / v["total"], 3)}
                         for k, v in sorted(per_type.items())},
            "wrong": wrong}


def test_golden_set_integrity():
    items = GOLDEN["items"]
    assert len(items) == 50 and len({i["id"] for i in items}) == 50
    for i in items:
        assert i["answer"] in {o["label"] for o in i["options"]}
        assert len(i["options"]) == 4


def test_eval_harness_runs():
    report = run_eval(DemoProvider())
    assert report["total"] == 50
    assert set(report["per_type"]) == {"grammar_mc", "vocabulary_mc", "synonym",
                                       "antonym", "cloze", "reading_comprehension"}
    print("\nEB-307 demo-provider accuracy:", report["accuracy"],
          {k: v["accuracy"] for k, v in report["per_type"].items()})
