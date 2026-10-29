"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearToken, getToken, ImportResult, ImportStats, QuestionItem, QuestionPage, ReviewQueue, SourceExam, Tag, Workspace } from "../lib/api";

export default function Home() {
  const router = useRouter();
  const [tab, setTab] = useState<"exams" | "bank" | "import" | "review" | "builder">("exams");
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [wsId, setWsId] = useState("");
  const [exams, setExams] = useState<SourceExam[]>([]);
  const [error, setError] = useState("");

  // Form tạo đề gốc
  const [title, setTitle] = useState("");
  const [grade, setGrade] = useState(12);
  const [kind, setKind] = useState("mid_term");

  // Kho câu hỏi
  const [units, setUnits] = useState<Tag[]>([]);
  const [bank, setBank] = useState<QuestionPage | null>(null);
  const [fUnit, setFUnit] = useState("");
  const [fType, setFType] = useState("");
  const [fDiff, setFDiff] = useState("");
  const [fStatus, setFStatus] = useState("approved");
  const [fSearch, setFSearch] = useState("");

  useEffect(() => {
    if (!getToken()) { router.push("/login"); return; }
    api<Workspace[]>("/api/v1/workspaces")
      .then((ws) => { setWorkspaces(ws); if (ws[0]) setWsId(ws[0].id); })
      .catch((e) => setError(e.message));
    api<Tag[]>("/api/v1/tags?kind=unit").then(setUnits).catch(() => {});
  }, [router]);

  const loadExams = useCallback(() => {
    if (!wsId) return;
    api<SourceExam[]>(`/api/v1/source-exams?workspace_id=${wsId}`).then(setExams).catch((e) => setError(e.message));
  }, [wsId]);
  useEffect(loadExams, [loadExams]);

  const loadBank = useCallback(() => {
    if (!wsId) return;
    const p = new URLSearchParams({ workspace_id: wsId, page_size: "20" });
    if (fUnit) p.set("unit", fUnit);
    if (fType) p.set("question_type", fType);
    if (fDiff) p.set("difficulty", fDiff);
    if (fStatus) p.set("status", fStatus);
    if (fSearch) p.set("search", fSearch);
    api<QuestionPage>(`/api/v1/question-items?${p}`).then(setBank).catch((e) => setError(e.message));
  }, [wsId, fUnit, fType, fDiff, fStatus, fSearch]);
  useEffect(() => { if (tab === "bank") loadBank(); }, [tab, loadBank]);

  async function createExam(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("/api/v1/source-exams", {
        method: "POST",
        body: JSON.stringify({ workspace_id: wsId, title, grade, exam_kind: kind }),
      });
      setTitle("");
      loadExams();
    } catch (err: any) { setError(err.message); }
  }

  // ---- EB-206: Nhập đề + Hàng đợi duyệt ----
  const pasteRef = useRef<HTMLDivElement>(null);
  const [impExamId, setImpExamId] = useState("");
  const [impStats, setImpStats] = useState<ImportStats | null>(null);
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [revDiff, setRevDiff] = useState<Record<string, string>>({});
  const [revUnit, setRevUnit] = useState<Record<string, string>>({});
  const [revAnswer, setRevAnswer] = useState<Record<string, string>>({});

  async function doImportPaste() {
    if (!impExamId) { setError("Hãy chọn đề gốc để nạp vào trước"); return; }
    const html = pasteRef.current?.innerHTML || "";
    if (!html.replace(/<[^>]*>/g, "").trim()) { setError("Ô dán đang trống — hãy dán nội dung đề vào"); return; }
    try {
      const r = await api<ImportResult>(`/api/v1/source-exams/${impExamId}/import`, {
        method: "POST", body: JSON.stringify({ mode: "paste_html", html }),
      });
      setImpStats(r.stats);
      loadQueue(impExamId);
    } catch (err: any) { setError(err.message); }
  }

  async function doImportDocx(file: File) {
    if (!impExamId) { setError("Hãy chọn đề gốc để nạp vào trước"); return; }
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api<ImportResult>(`/api/v1/source-exams/${impExamId}/import-docx`, { method: "POST", body: fd });
      setImpStats(r.stats);
      loadQueue(impExamId);
    } catch (err: any) { setError(err.message); }
  }

  const loadQueue = useCallback((examId: string) => {
    if (!examId) { setQueue(null); return; }
    api<ReviewQueue>(`/api/v1/source-exams/${examId}/review-queue`).then(setQueue).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { if (tab === "review" && impExamId) loadQueue(impExamId); }, [tab, impExamId, loadQueue]);

  async function doReview(q: QuestionItem, action: "approve" | "reject") {
    const body: Record<string, unknown> = { action };
    if (action === "approve") {
      if (revDiff[q.id]) body.difficulty = revDiff[q.id];
      if (revUnit[q.id]) body.tag_codes = [revUnit[q.id]];
      if (revAnswer[q.id]) body.correct_label = revAnswer[q.id];
    }
    try {
      await api(`/api/v1/question-items/${q.id}/review`, { method: "PATCH", body: JSON.stringify(body) });
      loadQueue(impExamId);
    } catch (err: any) { setError(err.message); }
  }

  const box: React.CSSProperties = { border: "1px solid #dde3ee", borderRadius: 12, padding: 16, marginBottom: 12, background: "#fff" };
  const btn: React.CSSProperties = { padding: "8px 14px", borderRadius: 999, border: "1px solid #c6d0e4", background: "#fff", cursor: "pointer", fontWeight: 650 };

  return (
    <main>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>ExamBank AI</h1>
        <button style={btn} onClick={() => { clearToken(); router.push("/login"); }}>Đăng xuất</button>
      </div>
      {error && <p style={{ color: "#b42318" }}>{error}</p>}
      <label>
        Workspace:{" "}
        <select value={wsId} onChange={(e) => setWsId(e.target.value)} style={{ padding: 8 }}>
          {workspaces.map((w) => (<option key={w.id} value={w.id}>{w.name}</option>))}
        </select>
      </label>

      <div style={{ display: "flex", gap: 8, margin: "16px 0", flexWrap: "wrap" }}>
        <button style={{ ...btn, ...(tab === "exams" ? { background: "#173a7a", color: "#fff" } : {}) }} onClick={() => setTab("exams")}>Đề gốc</button>
        <button style={{ ...btn, ...(tab === "bank" ? { background: "#173a7a", color: "#fff" } : {}) }} onClick={() => setTab("bank")}>Kho câu hỏi</button>
        <button style={{ ...btn, ...(tab === "import" ? { background: "#173a7a", color: "#fff" } : {}) }} onClick={() => setTab("import")}>Nhập đề</button>
        <button style={{ ...btn, ...(tab === "review" ? { background: "#173a7a", color: "#fff" } : {}) }} onClick={() => setTab("review")}>Duyệt câu hỏi</button>
        <button style={{ ...btn, ...(tab === "builder" ? { background: "#173a7a", color: "#fff" } : {}) }} onClick={() => setTab("builder")}>Tạo đề</button>
      </div>

      {tab === "exams" && (
        <section>
          <form onSubmit={createExam} style={{ ...box, display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input placeholder="Tên đề, VD: Giữa kỳ 1 — Lớp 12" value={title} onChange={(e) => setTitle(e.target.value)} required style={{ flex: 2, padding: 9 }} />
            <select value={grade} onChange={(e) => setGrade(Number(e.target.value))} style={{ padding: 9 }}>
              <option value={10}>Lớp 10</option><option value={11}>Lớp 11</option><option value={12}>Lớp 12</option>
            </select>
            <select value={kind} onChange={(e) => setKind(e.target.value)} style={{ padding: 9 }}>
              <option value="15min">15 phút</option><option value="45min">45 phút</option>
              <option value="mid_term">Giữa kỳ</option><option value="final">Cuối kỳ</option><option value="graduation">Tốt nghiệp</option>
            </select>
            <button style={{ padding: "9px 16px", background: "#173a7a", color: "#fff", border: 0, borderRadius: 8, fontWeight: 700 }}>+ Tạo đề gốc</button>
          </form>
          {exams.length === 0 && <p>Chưa có đề gốc nào trong workspace này.</p>}
          {exams.map((e) => (
            <div key={e.id} style={box}><b>{e.title}</b> — Lớp {e.grade} · {e.exam_kind}</div>
          ))}
        </section>
      )}

      {tab === "bank" && (
        <section>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
            <input placeholder="Tìm nội dung câu..." value={fSearch} onChange={(e) => setFSearch(e.target.value)} style={{ padding: 9 }} />
            <select value={fUnit} onChange={(e) => setFUnit(e.target.value)} style={{ padding: 9 }}>
              <option value="">Mọi Unit</option>
              {units.map((u) => (<option key={u.id} value={u.code}>{u.label}</option>))}
            </select>
            <select value={fType} onChange={(e) => setFType(e.target.value)} style={{ padding: 9 }}>
              <option value="">Mọi dạng bài</option><option value="grammar_mc">Ngữ pháp</option>
              <option value="vocabulary_mc">Từ vựng</option><option value="reading_comprehension">Đọc hiểu</option><option value="cloze">Đọc điền từ</option>
            </select>
            <select value={fDiff} onChange={(e) => setFDiff(e.target.value)} style={{ padding: 9 }}>
              <option value="">Mọi độ khó</option><option>NB</option><option>TH</option><option>VD</option><option>VDC</option>
            </select>
            <select value={fStatus} onChange={(e) => setFStatus(e.target.value)} style={{ padding: 9 }}>
              <option value="approved">Đã duyệt</option><option value="pending_review">Chờ duyệt</option><option value="">Mọi trạng thái</option>
            </select>
          </div>
          <p>Tổng: <b>{bank?.total ?? 0}</b> câu</p>
          {(bank?.items || []).map((q) => (
            <div key={q.id} style={box}>
              <b>{q.stem_text}</b>
              <div style={{ color: "#53627f", fontSize: 13, marginTop: 4 }}>
                {q.question_type} · {q.difficulty || "-"} · {q.status} · đáp án từ: {q.answer_source} · {q.tags.join(", ")}
              </div>
              <div style={{ fontSize: 13 }}>{q.options.map((o) => `${o.label}. ${o.content_text}`).join("   ")}</div>
            </div>
          ))}
          {bank && bank.total === 0 && <p>Không có câu nào khớp bộ lọc. Hãy nạp đề ở tab Nhập đề rồi duyệt ở tab Duyệt câu hỏi.</p>}
        </section>
      )}

      {tab === "import" && (
        <section>
          <div style={{ ...box, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <span>Nạp vào đề gốc:</span>
            <select value={impExamId} onChange={(e) => setImpExamId(e.target.value)} style={{ padding: 9 }}>
              <option value="">— Chọn đề gốc —</option>
              {exams.map((e) => (<option key={e.id} value={e.id}>{e.title}</option>))}
            </select>
            <label style={{ ...btn, display: "inline-block" }}>
              Hoặc tải file .docx
              <input type="file" accept=".docx" style={{ display: "none" }}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) doImportDocx(f); e.target.value = ""; }} />
            </label>
          </div>
          <p style={{ color: "#53627f", fontSize: 13 }}>
            Dán đề từ Word/PDF vào ô dưới (giữ nguyên đáp án tô đỏ hoặc highlight), mỗi câu bắt đầu bằng
            "Question 1:" và các phương án A. B. C. D. — hệ thống tự tách câu và nhận đáp án, không chắc thì để trống chờ duyệt.
          </p>
          <div ref={pasteRef} contentEditable suppressContentEditableWarning
            style={{ border: "1.5px dashed #9db4dd", borderRadius: 12, padding: 14, minHeight: 130, background: "#fbfcff" }} />
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button style={{ padding: "9px 16px", background: "#173a7a", color: "#fff", border: 0, borderRadius: 8, fontWeight: 700 }} onClick={doImportPaste}>
              Phân tích &amp; nạp vào kho
            </button>
            <button style={btn} onClick={() => { if (pasteRef.current) pasteRef.current.innerHTML = '<p>Question 1: She has lived here ______ 2010. A. for B. <span style="color:#ff0000">since</span> C. in D. at</p><p>Question 2: The room ______ every day. A. cleans B. <span style="color:#ff0000">is cleaned</span> C. cleaned D. cleaning</p>'; }}>
              Điền mẫu tô đỏ
            </button>
          </div>
          {impStats && (
            <p style={{ marginTop: 12 }}>
              Kết quả nạp: <b>{impStats.total}</b> câu · có đáp án <b>{impStats.with_answer}</b> · chờ bổ sung đáp án{" "}
              <b>{impStats.needs_answer}</b> · trùng bỏ qua <b>{impStats.duplicates}</b> · lỗi <b>{impStats.failed}</b>.
              Sang tab <b>Duyệt câu hỏi</b> để duyệt trước khi dùng sinh đề.
            </p>
          )}
        </section>
      )}

      {tab === "review" && (
        <section>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
            <span>Đề gốc:</span>
            <select value={impExamId} onChange={(e) => setImpExamId(e.target.value)} style={{ padding: 9 }}>
              <option value="">— Chọn đề gốc —</option>
              {exams.map((e) => (<option key={e.id} value={e.id}>{e.title}</option>))}
            </select>
            <span>Đang chờ duyệt: <b>{queue?.total ?? 0}</b> câu</span>
          </div>
          {queue && queue.total === 0 && <p>Hàng đợi trống — mọi câu của đề này đã được xử lý.</p>}
          {(queue?.items || []).map((q) => {
            const correctLabel = q.options.find((o) => o.id === q.correct_option_id)?.label;
            return (
              <div key={q.id} style={box}>
                {(q.passage_html || q.passage_text) && <div style={{ background: "#f4f7fd", padding: 10, borderRadius: 8, fontSize: 13, marginBottom: 8 }} dangerouslySetInnerHTML={{ __html: q.passage_html || q.passage_text || "" }} />}
                <div style={{ fontWeight: 650 }} dangerouslySetInnerHTML={{ __html: q.stem_html || q.stem_text }} />
                <div style={{ display: "grid", gap: 4, fontSize: 14, margin: "8px 0" }}>
                  {q.options.map((o) => (
                    <span key={o.id} style={o.label === (revAnswer[q.id] || correctLabel) ? { fontWeight: 700, color: "#12703a" } : {}}>
                      <span dangerouslySetInnerHTML={{ __html: `${o.label}. ${o.content_html || o.content_text}` }} />{o.label === correctLabel ? " ✓ (hệ thống nhận diện)" : ""}
                    </span>
                  ))}
                </div>
                <div style={{ color: "#53627f", fontSize: 13 }}>
                  Trạng thái: {q.status} · Nguồn đáp án: {q.answer_source}
                  {q.answer_confidence != null ? ` · độ tin cậy ${Math.round(q.answer_confidence * 100)}%` : ""}
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
                  <select value={revAnswer[q.id] || correctLabel || ""} onChange={(e) => setRevAnswer({ ...revAnswer, [q.id]: e.target.value })} style={{ padding: 8 }}>
                    <option value="">— Đáp án đúng —</option>
                    {q.options.map((o) => (<option key={o.id} value={o.label}>{o.label}</option>))}
                  </select>
                  <select value={revDiff[q.id] || ""} onChange={(e) => setRevDiff({ ...revDiff, [q.id]: e.target.value })} style={{ padding: 8 }}>
                    <option value="">— Độ khó —</option><option>NB</option><option>TH</option><option>VD</option><option>VDC</option>
                  </select>
                  <select value={revUnit[q.id] || ""} onChange={(e) => setRevUnit({ ...revUnit, [q.id]: e.target.value })} style={{ padding: 8 }}>
                    <option value="">— Unit —</option>
                    {units.map((u) => (<option key={u.id} value={u.code}>{u.label}</option>))}
                  </select>
                  <button style={{ padding: "8px 14px", background: "#12703a", color: "#fff", border: 0, borderRadius: 8, fontWeight: 700 }} onClick={() => doReview(q, "approve")}>Duyệt vào kho</button>
                  <button style={{ padding: "8px 14px", background: "#fff", color: "#b42318", border: "1px solid #e5b3ae", borderRadius: 8, fontWeight: 700 }} onClick={() => doReview(q, "reject")}>Loại bỏ</button>
                </div>
              </div>
            );
          })}
        </section>
      )}

      {tab === "builder" && (
        <section style={box}>
          <h3>Tạo đề</h3>
          <p>Sinh đề theo mẫu, hoán vị nhiều mã đề và xuất Word/PDF thuộc <b>EB-401 → EB-405, Tuần 4</b>.</p>
          <p>Điều kiện tiên quyết: kho phải có câu ở trạng thái đã duyệt — dữ liệu đó bắt đầu có từ Tuần 2.</p>
        </section>
      )}
    </main>
  );
}
