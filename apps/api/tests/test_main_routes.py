"""EB-406 — Chốt hồi quy: mọi router chính phải được ĐĂNG KÝ trong app (UAT vòng 1 từng
bắt lỗi exams router viết xong nhưng chưa include khiến /exam-templates trả 404)."""
from app.main import app

REQUIRED = {
    "/api/v1/exam-templates", "/api/v1/exams/generate", "/api/v1/exams/{exam_id}",
    "/api/v1/exams/{exam_id}/export/docx", "/api/v1/exams/{exam_id}/versions/{code}/print",
    "/api/v1/source-exams/{exam_id}/solve-ai", "/api/v1/question-items/{question_id}/solve-ai",
    "/api/v1/source-exams/{exam_id}/import", "/api/v1/source-exams/{exam_id}/review-queue",
}


def test_all_key_routes_registered():
    paths = {r.path for r in app.routes}
    assert REQUIRED.issubset(paths), REQUIRED - paths
