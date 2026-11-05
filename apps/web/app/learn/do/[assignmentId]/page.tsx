"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { api } from "../../../../lib/api";

interface Opt { option_id: string; label: string; content_html: string | null; content_text: string | null }
interface Q { position: number; question_id: string; question_type: string; stem_html: string | null; stem_text: string | null; passage: { key: string; title: string | null; content_html: string | null; content_text: string | null } | null; options: Opt[] }
interface AttemptStart { attempt_id: string; assignment_id: string; status: string; entry_method: string; questions: Q[]; answers: Record<string, string | null>; answer_release_at: string; show_score_immediately: boolean }
interface Result { status: string; score_raw?: number; score_max?: number; answer_released?: boolean; submitted_at?: string; answered_count: number; results?: { question_id: string; position: number; selected_option_id: string | null; correct_option_id: string; is_correct: boolean }[] }

function getUuid(key: string): string {
  let v = localStorage.getItem(key);
  if (!v) {
    v = (window.crypto?.randomUUID?.() ?? `uuid-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    localStorage.setItem(key, v);
  }
  return v;
}

export default function DoAssignmentPage({ params }: { params: { assignmentId: string } }) {
  const [att, setAtt] = useState<AttemptStart | null>(null);
  const [sel, setSel] = useState<Record<string, string | null>>({});
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<string>("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const uuidRef = useRef<string>("");

  useEffect(() => {
    (async () => {
      try {
        uuidRef.current = getUuid(`learn_attempt_${params.assignmentId}`);
        const mine = await api<any[]>("/api/v1/learn/my/assignments");
        const mineRow = mine.find((a) => a.assignment_id === params.assignmentId);
        setMode(mineRow?.mode ?? "");
      } catch {}
      try {
        const started = await api<AttemptStart>(`/api/v1/learn/assignments/${params.assignmentId}/attempts`, {
          method: "POST", body: JSON.stringify({ client_uuid: uuidRef.current }),
        });
        setAtt(started);
        setSel(started.answers ?? {});
        if (started.status === "submitted" || started.status === "graded" || started.status === "late") {
          const r = await api<Result>(`/api/v1/learn/attempts/${started.attempt_id}/result`);
          setResult(r);
        }
      } catch (e: any) { setError(e.message); }
    })();
  }, [params.assignmentId]);

  const total = att?.questions.length ?? 0;
  const answered = useMemo(() => Object.values(sel).filter(Boolean).length, [sel]);

  async function choose(qid: string, oid: string) {
    const next = { ...sel, [qid]: sel[qid] === oid ? null : oid };
    setSel(next);
    if (!att) return;
    try {
      await api(`/api/v1/learn/attempts/${att.attempt_id}/answer`, {
        method: "PATCH", body: JSON.stringify({ question_id: qid, selected_option_id: next[qid] }),
      });
    } catch (e: any) { setError(e.message); }
  }

  async function doSubmit() {
    if (!att) return;
    setSubmitting(true); setConfirmOpen(false);
    try {
      const r = await api<Result>(`/api/v1/learn/attempts/${att.attempt_id}/submit`, {
        method: "POST", body: JSON.stringify({ client_uuid: uuidRef.current }),
      });
      setResult(r);
    } catch (e: any) { setError(e.message); }
    setSubmitting(false);
  }

  function onSubmitClick() {
    if (answered < total) setConfirmOpen(true);
    else doSubmit();
  }

  if (error && !att) return <main><p className="learn-error">{error}</p><Link href="/learn">← Đề của tôi</Link></main>;
  if (!att) return <main><p className="learn-muted">Đang mở bài…</p></main>;

  const isPaper = (mode || att.entry_method) !== "online";
  const blanks = total - answered;

  const questionCard = (q: Q) => (
    <div key={q.question_id} style={{ marginBottom: 20 }}>
      <div className="text-body" style={{ fontWeight: 600 }}>Câu {q.position}</div>
      {q.stem_html && <div className="text-body" dangerouslySetInnerHTML={{ __html: q.stem_html }} />}
      <div role="radiogroup" aria-label={`Câu ${q.position}`} style={{ marginTop: 8 }}>
        {q.options.map((o) => (
          <button key={o.option_id} role="radio" aria-checked={sel[q.question_id] === o.option_id}
            className="radio-card" onClick={() => choose(q.question_id, o.option_id)}>
            <span style={{ fontWeight: 700, minWidth: 28 }}>{o.label}.</span>
            <span dangerouslySetInnerHTML={{ __html: o.content_html ?? o.content_text ?? "" }} />
          </button>
        ))}
      </div>
    </div>
  );

  const passageBox = (p: NonNullable<Q["passage"]>) => (
    <div key={p.key} className="passage-box">
      {p.title && <div style={{ fontWeight: 700, marginBottom: 6 }}>{p.title}</div>}
      <div className="text-passage" dangerouslySetInnerHTML={{ __html: p.content_html ?? p.content_text ?? "" }} />
    </div>
  );

  // Nhóm câu theo passage, giữ nguyên thứ tự
  const groups: { passage: Q["passage"]; qs: Q[] }[] = [];
  for (const q of att.questions) {
    const key = q.passage?.key ?? null;
    const last = groups[groups.length - 1];
    if (last && (last.passage?.key ?? null) === key) last.qs.push(q);
    else groups.push({ passage: q.passage, qs: [q] });
  }
  const passages = groups.filter((g) => g.passage).map((g) => g.passage!) as NonNullable<Q["passage"]>[];

  return (
    <main>
      <Link href="/learn">← Đề của tôi</Link>
      {error && <p className="learn-error">{error}</p>}

      {!result && (
        <>
          <h1 className="text-h1">{isPaper ? "Nhập đáp án" : "Làm bài online"}</h1>
          <p className="text-body learn-muted" aria-live="polite">
            Đã làm <b className="numeric">{answered}/{total}</b> câu — đáp án tự lưu khi chọn.
          </p>

          {isPaper ? (
            <section>
              {att.questions.map((q) => (
                <div key={q.question_id} className="entry-row">
                  <span className="text-body" style={{ fontWeight: 600 }}>Câu {q.position}</span>
                  <span className="learn-row" role="radiogroup" aria-label={`Câu ${q.position}`}>
                    {q.options.map((o) => (
                      <button key={o.option_id} className="opt-btn" aria-pressed={sel[q.question_id] === o.option_id}
                        onClick={() => choose(q.question_id, o.option_id)}>{o.label}</button>
                    ))}
                  </span>
                </div>
              ))}
            </section>
          ) : (
            <>
              {/* Desktop ≥1024: 2 cột (passage trái sticky, câu hỏi phải) — wireframe §2.3 */}
              <div className="online-cols online-desktop">
                <div className="online-passages">{passages.map(passageBox)}</div>
                <div>{att.questions.map(questionCard)}</div>
              </div>
              {/* Mobile: 1 cột cuộn chung, passage ngay trên câu đầu của nhóm */}
              <div className="online-mobile">
                {groups.map((g, i) => (
                  <div key={i}>
                    {g.passage && passageBox(g.passage)}
                    {g.qs.map(questionCard)}
                  </div>
                ))}
              </div>
              <style>{`@media (max-width: 1023px){.online-desktop{display:none}} @media (min-width: 1024px){.online-mobile{display:none}}`}</style>
            </>
          )}

          <div className="sticky-bar">
            <button className="learn-btn learn-btn-primary" style={{ width: "100%" }} disabled={submitting} onClick={onSubmitClick}>
              {submitting ? "Đang nộp…" : blanks > 0 ? `Nộp bài — còn ${blanks} câu chưa trả lời` : "Nộp bài"}
            </button>
          </div>

          {confirmOpen && (
            <div role="alertdialog" aria-modal="true" className="learn-card" style={{ borderColor: "var(--not-yet)" }}>
              <p className="text-body">Em còn <b>{blanks} câu chưa trả lời</b>. Nộp bài vẫn được — các câu trống tính là chưa làm. Em chắc chắn nộp chứ?</p>
              <div className="learn-row">
                <button className="learn-btn" onClick={() => setConfirmOpen(false)}>Làm tiếp</button>
                <button className="learn-btn learn-btn-primary" onClick={doSubmit}>Vẫn nộp bài</button>
              </div>
            </div>
          )}
        </>
      )}

      {result && (
        <section className="learn-card">
          <h2 className="text-h2">Đã nộp bài ✓</h2>
          {result.answer_released && result.score_raw !== undefined ? (
            <>
              <p className="text-h3">Đúng {result.score_raw}/{result.score_max} câu</p>
              {result.results?.map((r) => {
                const q = att.questions.find((x) => x.question_id === r.question_id);
                const correctLabel = q?.options.find((o) => o.option_id === r.correct_option_id)?.label;
                return (
                  <div key={r.question_id} className="learn-row" style={{ justifyContent: "space-between", borderBottom: "1px solid var(--border)", padding: "6px 0" }}>
                    <span>Câu {r.position}</span>
                    {r.is_correct
                      ? <span className="learn-ok">Đúng ✓</span>
                      : <span className="learn-notyet">Chưa đúng — đáp án: {correctLabel ?? "?"}</span>}
                  </div>
                );
              })}
            </>
          ) : result.score_raw !== undefined ? (
            <p className="text-body">Điểm: <b className="numeric">{result.score_raw}/{result.score_max}</b>. Chi tiết đáp án mở lúc {new Date(att.answer_release_at).toLocaleString("vi-VN")}.</p>
          ) : (
            <p className="text-body">
              Đã nhận bài lúc {result.submitted_at ? new Date(result.submitted_at).toLocaleString("vi-VN") : ""} · Đã làm {result.answered_count} câu.
              <br />Đáp án mở lúc {new Date(att.answer_release_at).toLocaleString("vi-VN")} — quay lại sau để xem đúng/sai từng câu nhé.
            </p>
          )}
          <Link href="/learn">← Về Đề của tôi</Link>
        </section>
      )}
    </main>
  );
}
