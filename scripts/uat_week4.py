"""EB-406 — UAT vòng 1: trọn vòng đời trên ĐỀ THẬT của Ha qua HTTP thật.

Luồng: đăng ký -> nạp 2 đề .docx thật (K12 Unit 10 đáp án đỏ, UNIT_5 highlight)
-> duyệt toàn bộ -> xem phân bố dạng bài trong kho -> sinh đề theo mẫu phù hợp
-> kiểm chứng bất biến đáp án sau hoán vị -> tải Word 3 bản và mở kiểm tra.
Chạy: /tmp/eb-venv/bin/python scripts/uat_week4.py (tự khởi động uvicorn cổng 8023)
"""
import io
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "apps" / "api"
FILES = Path.home() / "workspace" / "user" / "files"
DB = "/tmp/eb_uat.db"
BASE = "http://127.0.0.1:8023"

sys.path.insert(0, str(API_DIR))
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")


def init_db():
    try:
        os.remove(DB)
    except FileNotFoundError:
        pass
    os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import Base
    import app.models  # noqa: F401
    engine = create_engine(f"sqlite:///{DB}")
    Base.metadata.create_all(engine)
    from app.seed import seed_taxonomy, seed_templates
    db = sessionmaker(bind=engine)()
    print("seed taxonomy:", seed_taxonomy(db))
    print("seed templates:", seed_templates(db))
    db.close()


def main():
    init_db()
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{DB}",
               NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
    srv = subprocess.Popen(["/tmp/eb-venv/bin/uvicorn", "app.main:app", "--port", "8023"],
                           cwd=API_DIR, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import httpx
        from docx import Document
        c = httpx.Client(base_url=BASE, timeout=120, trust_env=False)
        for _ in range(60):
            try:
                c.get("/health"); break
            except Exception:
                time.sleep(0.5)
        reg = c.post("/api/v1/auth/register", json={
            "email": "uat@demo.edu", "password": "demo12345", "full_name": "UAT"}).json()
        H = {"Authorization": f"Bearer {reg['access_token']}"}
        ws = reg["default_workspace_id"]

        def import_docx(fname, title):
            ex = c.post("/api/v1/source-exams", headers=H, json={
                "workspace_id": ws, "title": title, "grade": 12, "exam_kind": "unit_test"}).json()
            with open(FILES / fname, "rb") as f:
                r = c.post(f"/api/v1/source-exams/{ex['id']}/import-docx", headers=H,
                           files={"file": (fname, f,
                                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
            r.raise_for_status()
            return ex["id"], r.json()

        for fname, title in [("K12_TEST_UNIT_10_LIFELONG_LEARNING.docx", "K12 Unit 10"),
                             ("UNIT_5_THE_WORLD_OF_WORK_GS12_NYEN__1.docx", "Unit 5 GS12")]:
            ex_id, res = import_docx(fname, title)
            print(f"import {title}: {res['stats']}")
            queue = c.get(f"/api/v1/source-exams/{ex_id}/review-queue", headers=H).json()
            ok = 0
            for item in queue["items"]:
                r = c.patch(f"/api/v1/question-items/{item['id']}/review", headers=H,
                            json={"action": "approve"})
                if r.status_code == 200:
                    ok += 1
                else:
                    print("  approve FAIL:", item["stem_text"][:50], r.status_code, r.text[:120])
            print(f"  approved {ok}/{queue['total']}")

        bank = c.get("/api/v1/question-items", headers=H,
                     params={"workspace_id": ws, "status": "approved", "page_size": 100}).json()
        print("bank approved page1 total:", bank["total"],
              "| types:", Counter(i["question_type"] for i in bank["items"]))

        templates = c.get("/api/v1/exam-templates", headers=H,
                          params={"workspace_id": ws}).json()["items"]
        # (a) Mẫu TN THPT trên kho thật này phải bị chặn 422 với lý do rõ ràng
        # (kho từ 2 đề thật dạng TN không có câu phát âm/trọng âm/ngữ pháp độc lập).
        tpl50 = next(t for t in templates if "TN THPT" in t["name"])
        gen50 = c.post("/api/v1/exams/generate", headers=H, json={
            "workspace_id": ws, "template_id": tpl50["id"], "n_versions": 1})
        print("generate TN-template on real bank:", gen50.status_code)
        if gen50.status_code == 422:
            msg = gen50.json()["detail"]["message"]
            print("  shortfall message:", msg[:220], "...")
        # (b) Template tự tạo khớp với kho thật (điền khuyết + đọc hiểu) -> sinh thành công
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models import ExamTemplate, TemplateSection
        sdb = sessionmaker(bind=create_engine(f"sqlite:///{DB}"))()
        custom = ExamTemplate(workspace_id=None, name="UAT — Đề luyện Điền khuyết + Đọc hiểu (24 câu)",
                              grade=12, total_questions=24, duration_minutes=30, is_system=False)
        # workspace_id gán sau khi flush theo ws thật:
        import uuid as _uuid
        custom.workspace_id = _uuid.UUID(ws)
        sdb.add(custom); sdb.flush()
        sdb.add_all([
            TemplateSection(template_id=custom.id, section_order=1, name="Điền khuyết",
                            question_type="cloze", passage_type="cloze", question_count=11,
                            difficulty_mix={}, tag_filter={}),
            TemplateSection(template_id=custom.id, section_order=2, name="Đọc hiểu",
                            question_type="reading_comprehension", passage_type="reading",
                            question_count=13, difficulty_mix={}, tag_filter={}),
        ])
        sdb.commit()
        custom_id = str(custom.id)
        sdb.close()
        gen = c.post("/api/v1/exams/generate", headers=H, json={
            "workspace_id": ws, "template_id": custom_id, "n_versions": 4, "seed": 1})
        print("generate custom template:", gen.status_code)
        if gen.status_code != 201:
            print("  detail:", gen.text[:600])
            print("UAT RESULT: generate FAILED")
            return
        exam = gen.json()
        detail = c.get(f"/api/v1/exams/{exam['id']}", headers=H).json()
        v1 = {it["question_id"]: it for it in detail["versions"][0]["items"]}
        print("versions:", [(v["code"], v["question_count"], v["answer_balance"]) for v in detail["versions"]])
        # Bất biến: nội dung đáp án đúng sau hoán vị phải khớp bản gốc ở mọi mã đề
        bad = 0
        bank_by_id = {i["id"]: i for i in bank["items"]}
        for v in detail["versions"]:
            for it in v["items"]:
                orig = bank_by_id[it["question_id"]]
                orig_correct = next(o["content_text"] for o in orig["options"]
                                    if o["id"] == orig["correct_option_id"])
                new_correct = next(o["text"] for o in it["options"]
                                   if o["label"] == it["correct_label"])
                if orig_correct != new_correct:
                    bad += 1
        print("answer-content invariant violations:", bad)
        # Câu chưa duyệt có lọt vào không: mọi question_id phải thuộc tập approved
        used_ids = {it["question_id"] for it in detail["versions"][0]["items"]}
        print("all used questions are approved:", used_ids.issubset(set(bank_by_id)))

        for kind in ("student", "teacher", "matrix"):
            r = c.get(f"/api/v1/exams/{exam['id']}/export/docx", headers=H,
                      params={"kind": kind})
            doc = Document(io.BytesIO(r.content))
            text = "\n".join(p.text for p in doc.paragraphs)
            print(f"docx {kind}: {len(r.content)} bytes, paragraphs={len(doc.paragraphs)}, "
                  f"has_title={'Mã đề' in text or 'MA TRẬN' in text}")
        pr = c.get(f"/api/v1/exams/{exam['id']}/versions/002/print", headers=H)
        print("print html v002:", pr.status_code, "Câu 1:" in pr.text, "len:", len(pr.text))
        print("UAT RESULT: DONE")
    finally:
        srv.terminate()


if __name__ == "__main__":
    main()
