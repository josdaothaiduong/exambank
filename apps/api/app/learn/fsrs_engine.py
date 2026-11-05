"""S1-F2 — FSRS engine: module DUY NHẤT bọc py-fsrs (fsrs==6.3.2).

Theo khuyến nghị tích hợp ở exambank-learn/spikes/fsrs/SPIKE-RESULT.md mục 5:
- Scheduler stateless, cache theo desired_retention của lớp (0.85-0.95).
- Tính on-demand khi HS nộp thẻ, không dùng Celery Beat để tính lịch
  (máy Windows tắt qua đêm không được làm hỏng lịch ôn).
- Mọi datetime phải timezone-aware UTC; hiển thị Asia/Ho_Chi_Minh ở client.
- enable_fuzzing=False để lịch tất định, test hồi quy so được số của spike.
- Không tối ưu tham số (Optimizer) ở MVP: dùng 21 tham số mặc định của thư viện.

Định dạng "state" (dict) khớp 1-1 với các cột của bảng review_cards
(fsrs_card_id, fsrs_state, fsrs_step, stability, fsrs_difficulty, due_at,
last_reviewed_at) và với Card.to_dict() của py-fsrs:

    {
        "card_id": int | None,        # fsrs_card_id
        "state": int,                 # 1 Learning, 2 Review, 3 Relearning
        "step": int | None,
        "stability": float | None,    # ngày; None trước lần ôn đầu
        "difficulty": float | None,   # thang 1-10 của FSRS
        "due": str,                   # ISO-8601 UTC (due_at)
        "last_review": str | None,    # ISO-8601 UTC (last_reviewed_at)
    }
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fsrs import Card, Rating, Scheduler

DEFAULT_RETENTION = 0.90
RETENTION_MIN, RETENTION_MAX = 0.85, 0.95  # khoảng cấu hình cấp lớp (DB-API-SPEC 2.3)
FSRS_PARAMS_VERSION = "fsrs-default-v6"

_scheduler_cache: dict[float, Scheduler] = {}

_RATING_BY_NAME = {
    "again": Rating.Again, "hard": Rating.Hard,
    "good": Rating.Good, "easy": Rating.Easy,
}


def _ensure_aware(dt: datetime, name: str = "datetime") -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{name} phai timezone-aware (UTC); nhan duoc datetime naive")
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt is not None else None


def _parse_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_aware(value)
    return _ensure_aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def get_scheduler(desired_retention: float = DEFAULT_RETENTION) -> Scheduler:
    """Trả Scheduler theo desired_retention, cache trong tiến trình.

    Scheduler của py-fsrs là stateless nên dùng chung an toàn giữa các request.
    """
    r = float(desired_retention)
    if not 0.0 < r < 1.0:
        raise ValueError(f"desired_retention phai trong (0, 1); nhan {desired_retention!r}")
    if r not in _scheduler_cache:
        _scheduler_cache[r] = Scheduler(desired_retention=r, enable_fuzzing=False)
    return _scheduler_cache[r]


def new_card_state(now: datetime) -> dict:
    """State của thẻ mới tinh tại thời điểm now (chưa ôn lần nào)."""
    return card_to_state(Card(), now_hint=_ensure_aware(now, "now"))


def card_to_state(card: Card, now_hint: datetime | None = None) -> dict:
    """Card của py-fsrs -> state dict lưu DB.

    Card() mới tinh có due là thời điểm tạo theo đồng hồ hệ thống; khi có
    now_hint (thẻ mới tạo trong request), chuẩn hoá due về now_hint cho tất định.
    """
    due = card.due
    if card.last_review is None and card.stability is None and now_hint is not None:
        due = now_hint
    return {
        "card_id": card.card_id,
        "state": int(card.state),
        "step": card.step,
        "stability": card.stability,
        "difficulty": card.difficulty,
        "due": _iso(due),
        "last_review": _iso(card.last_review),
    }


def card_from_state(state: dict | None) -> Card:
    """State dict lưu DB -> Card của py-fsrs. None/rỗng -> thẻ mới."""
    if not state:
        return Card()
    return Card(
        card_id=state.get("card_id"),
        state=state.get("state", 1),
        step=state.get("step"),
        stability=state.get("stability"),
        difficulty=state.get("difficulty"),
        due=_parse_dt(state.get("due")),
        last_review=_parse_dt(state.get("last_review")),
    )


def _coerce_rating(rating) -> Rating:
    if isinstance(rating, Rating):
        return rating
    if isinstance(rating, str):
        key = rating.strip().lower()
        if key in _RATING_BY_NAME:
            return _RATING_BY_NAME[key]
        raise ValueError(f"rating khong hop le: {rating!r} (dung again/hard/good/easy hoac 1-4)")
    value = int(rating)
    if value not in (1, 2, 3, 4):
        raise ValueError(f"rating phai trong 1-4 (1 Again, 2 Hard, 3 Good, 4 Easy); nhan {rating!r}")
    return Rating(value)


def apply_rating(state: dict | None, rating, now: datetime,
                 desired_retention: float = DEFAULT_RETENTION) -> tuple[dict, dict]:
    """Áp một rating tại thời điểm now. Trả (state_mới, log_dict).

    log_dict là dữ kiện để tầng service ghi vào review_logs (append-only)
    trong cùng transaction với việc cập nhật review_cards.
    """
    now = _ensure_aware(now, "now")
    scheduler = get_scheduler(desired_retention)
    before = card_to_state(card_from_state(state), now_hint=now) if state else new_card_state(now)
    card = card_from_state(state)
    new_card, review_log = scheduler.review_card(card, _coerce_rating(rating),
                                                 review_datetime=now)
    after = card_to_state(new_card)
    log = {
        "rating": int(review_log.rating),
        "reviewed_at": _iso(review_log.review_datetime),
        "state_before": before,
        "state_after": after,
        "scheduled_due_before": before["due"],
        "next_due_at": after["due"],
        "fsrs_params_version": FSRS_PARAMS_VERSION,
    }
    return after, log


def preview_intervals(state: dict | None, now: datetime,
                      desired_retention: float = DEFAULT_RETENTION) -> dict[int, dict]:
    """Khoảng ôn dự kiến cho cả 4 rating (UI hiện khoảng thật dưới mỗi nút).

    Chạy review_card trên 4 bản sao của thẻ, KHÔNG ghi DB.
    Trả {rating_int: {"due": iso, "interval": timedelta}}.
    """
    now = _ensure_aware(now, "now")
    scheduler = get_scheduler(desired_retention)
    out: dict[int, dict] = {}
    for rating in (Rating.Again, Rating.Hard, Rating.Good, Rating.Easy):
        probe = card_from_state(state)
        new_card, _ = scheduler.review_card(probe, rating, review_datetime=now)
        out[int(rating)] = {"due": _iso(new_card.due), "interval": new_card.due - now}
    return out


def due_queue(cards, now: datetime, limit: int = 35, new_limit: int = 20) -> list:
    """Helper thuần: lọc + sắp hàng đợi đến hạn từ danh sách thẻ.

    Mỗi phần tử là dict có tối thiểu "due_at" (datetime aware hoặc ISO str),
    tuỳ chọn "is_new" (bool) hoặc "reps" (0 = thẻ mới), "suspended_at".
    Quy tắc: bỏ thẻ suspended và thẻ chưa đến hạn; sắp theo due_at tăng dần
    (quá hạn lâu nhất trước); tối đa `limit` thẻ, trong đó thẻ mới không quá
    `new_limit` (trần thẻ mới/ngày — tham số, mặc định 20 theo Master Plan).
    """
    now = _ensure_aware(now, "now")
    due = []
    for card in cards:
        if card.get("suspended_at"):
            continue
        due_at = _parse_dt(card.get("due_at", card.get("due")))
        if due_at is None or due_at > now:
            continue
        due.append((due_at, card))
    due.sort(key=lambda pair: pair[0])
    out, new_seen = [], 0
    for _, card in due:
        if len(out) >= limit:
            break
        is_new = bool(card.get("is_new", card.get("reps", 1) == 0))
        if is_new:
            if new_seen >= new_limit:
                continue
            new_seen += 1
        out.append(card)
    return out
