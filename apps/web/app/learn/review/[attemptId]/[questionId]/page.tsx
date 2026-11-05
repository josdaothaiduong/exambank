"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "../../../../../lib/api";

interface OptBrief { option_id: string; label: string; content_text: string }
interface VariantOut { variant_id: string; stem_text: string; options: OptBrief[] }
interface Detail {
  question_id: string; stem_text: string; kind: string;
  your_option: OptBrief | null; correct_option: OptBrief | null;
  content_status: "ready" | "preparing"; error_code?: string | null;
  progress: { current_step: number; status: string; step1_correct: boolean | null; step3_correct: boolean | null; step4_correct: boolean | null };
  steps: null | {
    step1: { why_wrong: string; diagnosis_options: { key: string; text: string }[] };
    step2: { locked: boolean; cue?: string; rule?: string; why_correct?: string };
    step3: { locked: boolean; statements?: { key: string; text: string }[] };
    step4: { locked: boolean; variant?: VariantOut | null };
  };
}

const uuid = () =>
  (crypto as any).randomUUID ? crypto.randomUUID() : `u-${Date.now()}-${Math.random()}`;

export default function PostTestStepPage() {
  const params = useParams<{ attemptId: string; questionId: string }>();
  const base = `/api/v1/learn/attempts/${params.attemptId}/post-test/${params.questionId}`;
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [variantPick, setVariantPick] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setD(await api<Detail>(base)); }
    catch (e: any) { setError(e.message); }
  }, [base]);

  useEffect(() => { load(); }, [load]);

  async function postStep(body: any) {
    setError(""); setMsg("");
    try {
      const r = await api<{ is_correct: boolean | null }>(base + "/step", {
        method: "POST", body: JSON.stringify(body),
      });
      if (r.is_correct === false) setMsg("Chưa đúng — thử lại nhé, không sao cả.");
      await load();
    } catch (e: any) { setError(e.message); }
  }

  async function answerVariant() {
    if (!d?.steps?.step4.variant || !variantPick) return;
    setError(""); setMsg("");
    try {
      const r = await api<{ is_correct: boolean }>(base + "/variant-answer", {
        method: "POST",
        body: JSON.stringify({
          variant_id: d.steps.step4.variant.variant_id,
          selected_variant_option_id: variantPick,
          client_uuid: uuid(),
        }),
      });
      setMsg(r.is_correct
        ? "Đúng rồi — câu này đã sửa xong và sẽ quay lại theo lịch ôn."
        : "Chưa đúng — xem lại Bước 2 rồi thử lại biến thể nhé.");
      await load();
    } catch (e: any) { setError(e.message); }
  }

  if (error && !d) return <main><p className="learn-error">{error}</p><Link href={`/learn/review/${params.attemptId}`}>← Danh sách câu sai</Link></main>;
  if (!d) return <main><p className="learn-muted">Đang tải…</p></main>;

  const step = d.progress.current_step;
  return (
    <main>
      <Link href={`/learn/review/${params.attemptId}`}>← Danh sách câu sai</Link>
      <h1 className="text-h1" style={{ marginTop: 8 }}>Hậu-đề — 4 bước {d.progress.status === "completed" ? "· Đã sửa xong ✓" : `· Xong ${step}/4`}</h1>
      {error && <p className="learn-error">{error}</p>}
      {msg && <p className="learn-ok">{msg}</p>}
      <section className="learn-card">
        <p className="text-body">{d.stem_text}</p>
        <p className="text-body">
          Bạn chọn: <b>{d.your_option ? `${d.your_option.label}. ${d.your_option.content_text}` : "(bỏ trống)"}</b>
          {" · "}Đáp án đúng: <b>{d.correct_option ? `${d.correct_option.label}. ${d.correct_option.content_text}` : "?"}</b>
        </p>
      </section>

      {d.content_status === "preparing" && (
        <section className="learn-card"><p className="learn-notyet">Đang chuẩn bị phần giải thích… (thầy cô đang duyệt nội dung)</p></section>
      )}

      {d.steps && (
        <>
          <section className="learn-card">
            <h2 className="text-h2">Bước 1 — Vì sao đáp án bạn chọn chưa đúng?</h2>
            <p className="text-body">{d.steps.step1.why_wrong}</p>
            <p className="text-body"><b>Chạm vào lý do đúng nhất của em:</b></p>
            {d.steps.step1.diagnosis_options.map((o) => (
              <button key={o.key} className="radio-card" aria-checked={false}
                disabled={step >= 1}
                onClick={() => postStep({ step: 1, choice_key: o.key })}>
                {o.text}
              </button>
            ))}
            {d.progress.step1_correct === false && <p className="learn-notyet">Lý do đó chưa khớp — chọn lại nhé.</p>}
            {step >= 1 && <p className="learn-ok">Đã xong bước 1 ✓</p>}
          </section>

          <section className="learn-card">
            <h2 className="text-h2">Bước 2 — Vì sao đáp án đúng là đúng?</h2>
            {d.steps.step2.locked ? (
              <p className="learn-muted">(Mở sau khi làm xong Bước 1)</p>
            ) : (
              <>
                <p className="text-body"><b>Cue:</b> {d.steps.step2.cue}</p>
                <p className="text-body"><b>Quy tắc 1 câu:</b> {d.steps.step2.rule}</p>
                {step < 2
                  ? <button className="learn-btn learn-btn-primary" onClick={() => postStep({ step: 2 })}>Đã đọc — sang bước 3</button>
                  : <p className="learn-ok">Đã xong bước 2 ✓</p>}
              </>
            )}
          </section>

          <section className="learn-card">
            <h2 className="text-h2">Bước 3 — Cặp dễ nhầm: chạm vào (các) câu đúng</h2>
            {d.steps.step3.locked ? (
              <p className="learn-muted">(Mở sau khi làm xong Bước 2)</p>
            ) : (
              <>
                {d.steps.step3.statements?.map((s) => (
                  <button key={s.key} className="radio-card"
                    aria-checked={picked.has(s.key)}
                    onClick={() => setPicked((p) => { const n = new Set(p); n.has(s.key) ? n.delete(s.key) : n.add(s.key); return n; })}>
                    {s.text}
                  </button>
                ))}
                {step < 3
                  ? <button className="learn-btn learn-btn-primary" disabled={!picked.size}
                      onClick={() => postStep({ step: 3, selected_keys: [...picked] })}>Kiểm tra bước 3</button>
                  : <p className="learn-ok">Đã xong bước 3 ✓</p>}
                {d.progress.step3_correct === false && step < 3 && <p className="learn-notyet">Chưa đúng — kiểm tra lại từng câu nhé.</p>}
              </>
            )}
          </section>

          <section className="learn-card">
            <h2 className="text-h2">Bước 4 — Thử lại bằng một câu khác</h2>
            {d.steps.step4.locked ? (
              <p className="learn-muted">(Mở sau khi làm xong Bước 3)</p>
            ) : d.steps.step4.variant ? (
              <>
                <p className="text-body">{d.steps.step4.variant.stem_text}</p>
                {d.steps.step4.variant.options.map((o) => (
                  <button key={o.option_id} className="radio-card"
                    aria-checked={variantPick === o.option_id}
                    onClick={() => setVariantPick(o.option_id)}>
                    {o.label}. {o.content_text}
                  </button>
                ))}
                {d.progress.status !== "completed" && (
                  <button className="learn-btn learn-btn-primary" disabled={!variantPick} onClick={answerVariant}>Trả lời biến thể</button>
                )}
                {d.progress.status === "completed" && <p className="learn-ok">Đã xong bước 4 ✓ — câu này sẽ quay lại vào ngày mai, rồi giãn dần nếu bạn làm đúng.</p>}
              </>
            ) : (
              <p className="learn-notyet">Câu thử lại đang được thầy cô chuẩn bị — bạn có thể quay lại sau.</p>
            )}
          </section>
        </>
      )}
    </main>
  );
}
