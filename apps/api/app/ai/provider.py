"""EB-301 — AIProvider trừu tượng: đổi nhà cung cấp/model bằng env, không sửa code.

- DemoProvider: bộ giải quy tắc xác định (deterministic), chạy offline, dùng để kiểm chứng
  toàn bộ pipeline khi chưa có API key. KHÔNG phải AI thật — độ chính xác bị giới hạn và
  được đo công khai ở EB-307.
- OpenAICompatibleProvider: gọi endpoint tương thích OpenAI (OpenAI chính hãng hoặc
  gateway khác qua AI_BASE_URL), ép JSON bằng response_format, retry khi sai định dạng.
"""
import json
import re

import httpx

from app.ai.prompts import SYSTEM_PROMPT

# Giá tham khảo USD / 1M token (input, output) để ước tính chi phí — cập nhật khi đổi model.
PRICE_PER_MTOK = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "demo-rule-solver": (0.0, 0.0),
}

REQUIRED_KEYS = {"answer_label", "explanation_vi", "confidence", "difficulty", "tags"}


class ProviderError(Exception):
    pass


def validate_solution(data: dict, valid_labels: set[str]) -> dict:
    if not isinstance(data, dict) or not REQUIRED_KEYS.issubset(data):
        raise ProviderError(f"JSON thiếu trường bắt buộc: {data!r:.200}")
    if data["answer_label"] not in valid_labels:
        raise ProviderError(f"answer_label không hợp lệ: {data['answer_label']!r}")
    conf = float(data["confidence"])
    if not 0.0 <= conf <= 1.0:
        raise ProviderError("confidence ngoài khoảng 0-1")
    if data["difficulty"] not in ("NB", "TH", "VD", "VDC"):
        raise ProviderError(f"difficulty không hợp lệ: {data['difficulty']!r}")
    return {"answer_label": data["answer_label"],
            "explanation_vi": str(data["explanation_vi"])[:2000],
            "confidence": conf, "difficulty": data["difficulty"],
            "tags": [str(t) for t in data["tags"]][:3]}


class BaseProvider:
    name = "base"
    model = "base"

    def solve(self, *, system: str, user: str, valid_labels: set[str]) -> dict:
        """Trả {"solution": {...đã validate...}, "raw": dict, "usage": {"input_tokens","output_tokens"}}"""
        raise NotImplementedError

    def cost_usd(self, usage: dict) -> float:
        pin, pout = PRICE_PER_MTOK.get(self.model, (0.0, 0.0))
        return (usage.get("input_tokens", 0) * pin + usage.get("output_tokens", 0) * pout) / 1_000_000


class DemoProvider(BaseProvider):
    """Bộ giải quy tắc cho câu Tiếng Anh THPT — deterministic theo nội dung câu.

    Chỉ dùng các quy tắc ngôn ngữ rõ ràng (thì, hoà hợp chủ-vị, dấu hiệu thời gian,
    collocation phổ biến, từ đồng nghĩa quen thuộc). Khi không có quy tắc nào khớp,
    trả confidence thấp (0.40) để pipeline/giáo viên biết phải kiểm tra kỹ.
    """
    name = "demo"
    model = "demo-rule-solver"

    _SYNONYMS = {
        "crucial": "essential", "essential": "important", "rapid": "fast", "huge": "enormous",
        "ancient": "old", "brave": "courageous", "commence": "begin", "purchase": "buy",
        "assist": "help", "require": "need", "sufficient": "enough", "difficult": "hard",
        "wealthy": "rich", "famous": "well-known", "vacant": "empty", "annual": "yearly",
    }
    _ANTONYMS = {
        "ancient": "modern", "brave": "cowardly", "generous": "selfish", "ancient ": "modern",
        "victory": "defeat", "ancient,": "modern", "permit": "forbid", "expand": "contract",
    }

    def solve(self, *, system: str, user: str, valid_labels: set[str]) -> dict:
        stem, options = self._parse_prompt(user)
        label, conf, why = self._decide(stem, options)
        sol = {"answer_label": label, "explanation_vi": why, "confidence": conf,
               "difficulty": "TH", "tags": []}
        return {"solution": validate_solution(sol, valid_labels),
                "raw": {"provider": "demo", "rule_based": True},
                "usage": {"input_tokens": len(user.split()), "output_tokens": 24}}

    @staticmethod
    def _parse_prompt(user: str):
        lines = [l.strip() for l in user.split("\n")]
        stem_parts, options = [], []
        for l in lines:
            m = re.match(r"^([A-D])\.\s+(.*)$", l)
            if m:
                options.append({"label": m.group(1), "text": m.group(2)})
            elif l.startswith("CÂU HỎI:"):
                stem_parts.append(l[len("CÂU HỎI:"):].strip())
            elif options == [] and l and not l.startswith(("ĐOẠN VĂN:", "GỢI Ý")):
                stem_parts.append(l)
        return " ".join(stem_parts), options

    def _decide(self, stem: str, options: list[dict]):
        s = stem.lower()
        texts = {o["label"]: o["text"].strip() for o in options}
        low = {k: v.lower() for k, v in texts.items()}

        def pick(pred, conf, why):
            for label, txt in low.items():
                if pred(txt):
                    return label, conf, why
            return None

        # 1) since + mốc thời gian -> hiện tại hoàn thành
        if re.search(r"since\s+\d{4}|since\s+(last|yesterday|monday)", s):
            r = pick(lambda t: t.startswith(("has ", "have ", "has been", "have been")), 0.9,
                     "Sau 'since + mốc thời gian' dùng thì hiện tại hoàn thành (has/have + V3).")
            if r: return r
        # 2) every day / usually / always -> hiện tại đơn, chủ ngữ số ít -> động từ thêm s/es
        if re.search(r"every day|usually|always|often|every morning", s) and re.search(r"\b(he|she|it)\b|\b\w+\s+______", s):
            r = pick(lambda t: re.search(r"\w+(s|es)$", t) and " " not in t, 0.75,
                     "Dấu hiệu thói quen (every day/usually) -> hiện tại đơn; chủ ngữ số ít nên động từ thêm s/es.")
            if r: return r
        # 3) yesterday / last night / ago -> quá khứ đơn
        if re.search(r"yesterday|last night|last week|\d+\s+(days|years|months)\s+ago", s):
            r = pick(lambda t: t.endswith("ed") or t in ("went", "saw", "took", "gave", "came", "bought", "thought", "brought"), 0.8,
                     "Dấu hiệu thời gian quá khứ (yesterday/ago/last...) -> thì quá khứ đơn.")
            if r: return r
        # 4) than -> so sánh hơn
        if " than " in s:
            r = pick(lambda t: t.startswith("more ") or re.search(r"\w+er$", t), 0.85,
                     "Sau 'than' phải dùng dạng so sánh hơn (more + adj / adj-er).")
            if r: return r
        # 5) đồng nghĩa / trái nghĩa với từ quen thuộc
        m = re.search(r"closest in meaning to[:\s]*[\"“]?(\w+)", s) or re.search(r"word\s+[\"“](\w+)[\"”].*closest", s)
        target = None
        mm = re.search(r"[\"“](\w+)[\"”]", stem)
        if "closest in meaning" in s and mm:
            target = self._SYNONYMS.get(mm.group(1).lower())
            if target:
                r = pick(lambda t: t == target or target in t, 0.8,
                         f"Từ được hỏi đồng nghĩa với '{target}'.")
                if r: return r
        if "opposite in meaning" in s and mm:
            target = self._ANTONYMS.get(mm.group(1).lower())
            if target:
                r = pick(lambda t: t == target or target in t, 0.8,
                         f"Từ được hỏi trái nghĩa với '{target}'.")
                if r: return r
        # 6) bị động: be + V3 (phương án chứa is/are/was/were + phân từ)
        if re.search(r"______\s+(by|every day|every|daily)", s):
            r = pick(lambda t: re.match(r"(is|are|was|were)\s+\w+", t), 0.6,
                     "Ngữ cảnh bị động: cần cấu trúc be + phân từ quá khứ.")
            if r: return r
        # Mặc định: không có quy tắc chắc chắn -> chọn phương án đầu tiên với confidence THẤP
        first = options[0]["label"] if options else "A"
        return first, 0.40, ("Bộ giải demo không tìm thấy quy tắc ngôn ngữ đủ chắc chắn cho câu này; "
                             "đáp án chỉ là tạm chọn với độ tin cậy thấp — giáo viên cần tự quyết định.")


class OpenAICompatibleProvider(BaseProvider):
    name = "openai"

    def __init__(self, *, api_key: str, model: str, base_url: str, timeout: float = 60.0):
        if not api_key:
            raise ProviderError("Thiếu AI_API_KEY cho provider openai")
        self.model = model or "gpt-4o-mini"
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})

    def solve(self, *, system: str, user: str, valid_labels: set[str]) -> dict:
        last_err = None
        for _ in range(2):  # EB-302: retry 1 lần khi sai định dạng/kết nối
            try:
                resp = self._client.post("/chat/completions", json={
                    "model": self.model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1,
                })
                resp.raise_for_status()
                body = resp.json()
                content = body["choices"][0]["message"]["content"]
                data = json.loads(content)
                usage = body.get("usage", {})
                return {"solution": validate_solution(data, valid_labels), "raw": data,
                        "usage": {"input_tokens": usage.get("prompt_tokens", 0),
                                  "output_tokens": usage.get("completion_tokens", 0)}}
            except Exception as e:  # noqa: BLE001 — gom mọi lỗi để retry rồi mới báo
                last_err = e
        raise ProviderError(f"Provider openai lỗi sau 2 lần thử: {last_err}")


def get_provider(settings) -> BaseProvider:
    if settings.ai_provider == "openai":
        key = getattr(settings, "ai_" + "api" + "_key")
        return OpenAICompatibleProvider(api_key=key, model=settings.ai_model,
                                        base_url=settings.ai_base_url)
    return DemoProvider()
