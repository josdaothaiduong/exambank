from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Tag
from app.seed import seed_taxonomy
from app.taxonomy import GLOBAL_SUCCESS_UNITS, build_tag_specs


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Tag.__table__])
    return sessionmaker(bind=engine)()


def test_specs_shape():
    specs = build_tag_specs()
    # 3 grade + 1 textbook + 30 unit + 15 question_type + 5 skill + 4 difficulty + 10 topic
    assert len(specs) == 68
    assert len({(s["kind"], s["code"]) for s in specs}) == 68  # không trùng khóa
    for grade in (10, 11, 12):
        assert len(GLOBAL_SUCCESS_UNITS[grade]) == 10


def test_seed_is_idempotent_and_units_per_grade():
    db = _session()
    r1 = seed_taxonomy(db)
    assert r1["created"] == 68 and r1["total_in_db"] == 68
    r2 = seed_taxonomy(db)  # chạy lần 2: không tạo thêm gì
    assert r2["created"] == 0 and r2["total_in_db"] == 68

    for grade in (10, 11, 12):
        units = db.query(Tag).filter(
            Tag.kind == "unit", Tag.code.like(f"gs{grade}_unit%")).all()
        assert len(units) == 10, f"grade {grade}: {len(units)} units"
        assert all(u.parent_id is not None for u in units)  # Unit phải có parent là Grade

    gs12_u3 = db.query(Tag).filter_by(code="gs12_unit3").one()
    assert gs12_u3.label == "Unit 3: Green Living"
    assert db.query(Tag).filter_by(kind="difficulty").count() == 4
    assert db.query(Tag).filter_by(kind="question_type").count() == 15
