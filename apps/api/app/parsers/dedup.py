"""EB-205 — Chống trùng: hash nội dung đã chuẩn hóa (giống hệt quy ước ở Bước 1 + prototype)."""
import hashlib
import re


def dedup_hash(stem_text: str, option_texts: list[str]) -> str:
    norm = (stem_text + "|" + "|".join(sorted(option_texts))).lower()
    norm = re.sub(r"\s+", " ", norm).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()
