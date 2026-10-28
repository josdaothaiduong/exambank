"""EB-103 — Seed taxonomy, idempotent: chạy bao nhiêu lần cũng không tạo trùng.

Chạy:  python -m app.seed
Cơ chế: tra theo khóa duy nhất (kind, code) của bảng tags; có rồi thì cập nhật label/parent.
"""
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Tag
from app.taxonomy import build_tag_specs


def seed_taxonomy(db: Session) -> dict:
    specs = build_tag_specs()
    created, updated = 0, 0
    by_code = {}
    # Pass 1: tạo/cập nhật mọi tag (chưa gán parent)
    for spec in specs:
        tag = db.query(Tag).filter_by(kind=spec["kind"], code=spec["code"]).one_or_none()
        if tag is None:
            tag = Tag(kind=spec["kind"], code=spec["code"], label=spec["label"])
            db.add(tag)
            created += 1
        elif tag.label != spec["label"]:
            tag.label = spec["label"]
            updated += 1
        db.flush()
        by_code[spec["code"]] = tag
    # Pass 2: gán parent (Unit -> Grade)
    for spec in specs:
        if spec["parent_code"]:
            tag = by_code[spec["code"]]
            parent = by_code.get(spec["parent_code"]) or db.query(Tag).filter_by(code=spec["parent_code"]).one()
            if tag.parent_id != parent.id:
                tag.parent_id = parent.id
    db.commit()
    return {"total_specs": len(specs), "created": created, "updated": updated,
            "total_in_db": db.query(Tag).count()}


if __name__ == "__main__":
    with SessionLocal() as session:
        result = seed_taxonomy(session)
    print("Seed taxonomy:", result)
