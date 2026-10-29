"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearToken, getToken, ConflictResult, ExamTemplate, GeneratedExam, ImportResult, ImportStats, QuestionItem, QuestionPage, ReviewQueue, SolveResult, SourceExam, Tag, Workspace } from "../lib/api";

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
  const [nearDups, setNearDups] = useState<{ number: number; stem_text: string; similarity: number }[]>([]);
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [revDiff, setRevDiff] = useState<Record<string, string>>({});
  const [revUnit, setRevUnit] = useState<Record<string, string>>({});
  const [revAnswer, setRevAnswer] = useState<Record<string, string>>({});

  // ---- Trùng lặp kiểu Windows Explorer: trùng >= 40% thì dừng hỏi trước khi nạp ----
  const [conflict, setConflict] = useState<ConflictResult | null>(null);
  const [decisions, setDecisions] = useState<Record<string, "overwrite" | "keep">>({});
  const lastSourceRef = useRef<{ kind: "paste"; html: string } | { kind: "docx"; file: File } | null>(null);

  function handleImportResult(r: ImportResult | ConflictResult) {
    if (r.status === "conflict") {
      const c = r as ConflictResult;
      setConflict(c);
      setDecisions(Object.fromEntries(c.duplicates.map((d) => [d.dedup_hash, "keep" as const])));
      setImpStats(null);
    } else {
      setConflict(null);
      setImpStats((r as ImportResult).stats);
      setNearDups((r as ImportResult).near_duplicates || []);
      loadQueue(impExamId);
    }
  }

  async function runImport(onConflict: string, dec?: Record<string, string>) {
    const src = lastSourceRef.current;
    if (!src || !impExamId) return;
    try {
      if (src.kind === "paste") {
        const r = await api<ImportResult | ConflictResult>(`/api/v1/source-exams/${impExamId}/import`, {
          method: "POST",
          body: JSON.stringify({ mode: "paste_html", html: src.html, on_conflict: onConflict, decisions: dec || null }),
        });
        handleImportResult(r);
      } else {
        const fd = new FormData();
        fd.append("file", src.file);
        fd.append("on_conflict", onConflict);
        if (dec) fd.append("decisions_json", JSON.stringify(dec));
        const r = await api<ImportResult | ConflictResult>(`/api/v1/source-exams/${impExamId}/import-docx`, { method: "POST", body: fd });
        handleImportResult(r);
      }
    } catch (err: any) { setError(err.message); }
  }

  async function doImportPaste() {
    if (!impExamId) { setError("Hãy chọn đề gốc để nạp vào trước"); return; }
    const html = pasteRef.current?.innerHTML || "";
    if (!html.replace(/<[^>]*>/g, "").trim()) { setError("Ô dán đang trống — hãy dán nội dung đề vào"); return; }
    lastSourceRef.current = { kind: "paste", html };
    runImport("ask");
  }

  async function doImportDocx(file: File) {
    if (!impExamId) { setError("Hãy chọn đề gốc để nạp vào trước"); return; }
    lastSourceRef.current = { kind: "docx", file };
    runImport("ask");
  }

  const [solveMsg, setSolveMsg] = useState("");
  const [templates, setTemplates] = useState<ExamTemplate[]>([]);
  const [genTplId, setGenTplId] = useState("");
  const [genTitle, setGenTitle] = useState("");
  const [genVersions, setGenVersions] = useState(4);
  const [genExam, setGenExam] = useState<GeneratedExam | null>(null);
  const [genShortfall, setGenShortfall] = useState("");
  const [prevCode, setPrevCode] = useState("001");
  const [prevTeacher, setPrevTeacher] = useState(false);

  const loadTemplates = useCallback(() => {
    if (!wsId) return;
    api<{ items: ExamTemplate[] }>(`/api/v1/exam-templates?workspace_id=${wsId}`)
      .then((r) => { setTemplates(r.items); if (!genTplId && r.items.length) setGenTplId(r.items[0].id); })
      .catch((e: any) => setError(e.message));
  }, [wsId]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (tab === "builder") loadTemplates(); }, [tab, loadTemplates]);

  // ===== Mẫu đề tự chế =====
  interface TplSectionForm { name: string; question_type: string; question_count: number; with_passage: boolean; nb: string; th: string; vd: string; vdc: string }
  const [qtypes, setQtypes] = useState<Tag[]>([]);
  const [avail, setAvail] = useState<Record<string, { standalone: number; with_passage: number; total: number }>>({});
  const [editTplId, setEditTplId] = useState<string | null>(null);
  const [tplName, setTplName] = useState("");
  const [tplGrade, setTplGrade] = useState("");
  const [tplDuration, setTplDuration] = useState(30);
  const [tplSections, setTplSections] = useState<TplSectionForm[]>([
    { name: "Phần 1", question_type: "grammar_mc", question_count: 5, with_passage: false, nb: "", th: "", vd: "", vdc: "" },
  ]);
  const PASSAGE_TYPES = ["cloze", "reading_comprehension", "reading_announcement"];

  const loadAvail = useCallback(() => {
    if (!wsId) return;
    api<{ items: { question_type: string; standalone: number; with_passage: number; total: number }[] }>(
      `/api/v1/exam-templates/availability?workspace_id=${wsId}`)
      .then((r) => setAvail(Object.fromEntries(r.items.map((a) => [a.question_type, a]))))
      .catch(() => {});
    api<Tag[]>(`/api/v1/tags?kind=question_type`).then(setQtypes).catch(() => {});
  }, [wsId]);
  useEffect(() => { if (tab === "builder") loadAvail(); }, [tab, loadAvail]);

  function setSection(i: number, patch: Partial<TplSectionForm>) {
    setTplSections((prev) => prev.map((s, j) => {
      if (j !== i) return s;
      const next = { ...s, ...patch };
      if (patch.question_type) next.with_passage = PASSAGE_TYPES.includes(patch.question_type);
      return next;
    }));
  }

  async function saveTemplate() {
    const payload = {
      workspace_id: wsId, name: tplName || "Mẫu chưa đặt tên",
      grade: tplGrade ? Number(tplGrade) : undefined, duration_minutes: tplDuration,
      sections: tplSections.map((s) => ({
        name: s.name, question_type: s.question_type, question_count: s.question_count,
        with_passage: s.with_passage,
        difficulty_mix: Object.fromEntries(
          ([["NB", s.nb], ["TH", s.th], ["VD", s.vd], ["VDC", s.vdc]] as [string, string][])
            .filter(([, v]) => v !== "" && Number(v) > 0)
            .map(([k, v]) => [k, Number(v) / 100])),
      })),
    };
    try {
      const saved = editTplId
        ? await api<ExamTemplate>(`/api/v1/exam-templates/${editTplId}`, { method: "PUT", body: JSON.stringify(payload) })
        : await api<ExamTemplate>(`/api/v1/exam-templates`, { method: "POST", body: JSON.stringify(payload) });
      setEditTplId(null); setTplName("");
      loadTemplates(); setGenTplId(saved.id);
    } catch (e: any) { setError(e.message); }
  }

  function editTemplate(tp: ExamTemplate) {
    setEditTplId(tp.id); setTplName(tp.name);
    setTplGrade(tp.grade ? String(tp.grade) : ""); setTplDuration(tp.duration_minutes);
    setTplSections(tp.sections.map((s) => ({
      name: s.name, question_type: s.question_type, question_count: s.question_count,
      with_passage: !!s.passage_type,
      nb: s.difficulty_mix?.NB ? String(Math.round(s.difficulty_mix.NB * 100)) : "",
      th: s.difficulty_mix?.TH ? String(Math.round(s.difficulty_mix.TH * 100)) : "",
      vd: s.difficulty_mix?.VD ? String(Math.round(s.difficulty_mix.VD * 100)) : "",
      vdc: s.difficulty_mix?.VDC ? String(Math.round(s.difficulty_mix.VDC * 100)) : "",
    })));
  }

  async function removeTemplate(tp: ExamTemplate) {
    if (!window.confirm(`Xoá mẫu "${tp.name}"?`)) return;
    try {
      await api(`/api/v1/exam-templates/${tp.id}`, { method: "DELETE" });
      loadTemplates();
    } catch (e: any) { setError(e.message); }
  }

  async function doGenerate() {
    setGenShortfall(""); setGenExam(null);
    try {
      const r = await api<GeneratedExam>("/api/v1/exams/generate", {
        method: "POST",
        body: JSON.stringify({ workspace_id: wsId, template_id: genTplId, title: genTitle || undefined, n_versions: genVersions }),
      });
      const detail = await api<GeneratedExam>(`/api/v1/exams/${r.id}`);
      setGenExam(detail); setPrevCode("001");
    } catch (e: any) {
      let msg = e.message;
      try {
        const parsed = JSON.parse(msg);
        if (parsed.message) {
          msg = parsed.message + (parsed.shortfalls || []).map((s: any) => `\n• ${s.section}: cần ${s.needed}, kho có ${s.available}`).join("");
        }
      } catch {}
      setGenShortfall(msg);
    }
  }

  async function downloadDocx(kind: string, version?: string) {
    if (!genExam) return;
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/exams/${genExam.id}/export/docx?kind=${kind}${version ? `&version=${version}` : ""}`,
      { headers: { Authorization: `Bearer ${getToken()}` } });
    if (!res.ok) { setError("Tải Word thất bại"); return; }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `de-${kind}${version ? "-" + version : ""}.docx`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function openPrint(teacher: boolean) {
    if (!genExam) return;
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/exams/${genExam.id}/versions/${prevCode}/print?teacher=${teacher}`,
      { headers: { Authorization: `Bearer ${getToken()}` } });
    const htmlText = await res.text();
    const w = window.open("", "_blank");
    if (w) { w.document.write(htmlText); w.document.close(); }
  }
  async function doSolveAI() {
    if (!impExamId) { setError("Hãy chọn đề gốc trước"); return; }
    setSolveMsg("Đang giải bằng AI...");
    try {
      const r = await api<SolveResult>(`/api/v1/source-exams/${impExamId}/solve-ai`, { method: "POST" });
      setSolveMsg(`AI (${r.model}) đã giải ${r.solved}/${r.total} câu · ${r.low_confidence} câu độ tin cậy thấp cần kiểm tra kỹ · chi phí ước tính $${r.cost_usd.toFixed(4)}.`);
      loadQueue(impExamId);
    } catch (err: any) { setError(err.message); setSolveMsg(""); }
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
          {conflict && (
            <div style={{ border: "2px solid #d97706", borderRadius: 12, padding: 16, marginTop: 14, background: "#fffbeb" }}>
              <h3 style={{ marginTop: 0 }}>⚠ Đề này đã có phần lớn nội dung trong kho</h3>
              <p>
                Hệ thống phát hiện <b>{conflict.duplicate_count}/{conflict.total} câu ({Math.round(conflict.overlap_ratio * 100)}%)</b> đã
                tồn tại trong kho — vượt ngưỡng cảnh báo {Math.round(conflict.threshold * 100)}%. Chưa có gì được nạp.
                Bạn muốn xử lý các câu trùng thế nào? (Còn <b>{conflict.new_count} câu mới</b> sẽ được nạp trong mọi trường hợp.)
              </p>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
                <button style={{ padding: "9px 14px", background: "#b45309", color: "#fff", border: 0, borderRadius: 8, fontWeight: 700 }} onClick={() => runImport("overwrite")}>
                  Ghi đè tất cả câu trùng bằng bản mới
                </button>
                <button style={{ padding: "9px 14px", background: "#173a7a", color: "#fff", border: 0, borderRadius: 8, fontWeight: 700 }} onClick={() => runImport("keep_old")}>
                  Giữ bản cũ — chỉ nạp {conflict.new_count} câu mới
                </button>
                <button style={btn} onClick={() => setConflict(null)}>Huỷ — không nạp gì cả</button>
              </div>
              <p style={{ fontSize: 13, color: "#53627f", margin: "4px 0 10px" }}>
                Hoặc xem từng câu bên dưới, chọn riêng cho từng câu rồi bấm "Áp dụng lựa chọn từng câu". Lưu ý: câu đã duyệt mà bị ghi đè sẽ quay về trạng thái chờ duyệt.
              </p>
              {conflict.duplicates.map((d) => (
                <div key={d.dedup_hash} style={{ border: "1px solid #e5d9b8", borderRadius: 10, padding: 12, marginBottom: 10, background: "#fff" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: "#b45309" }}>BẢN MỚI NẠP — Câu {d.number}</div>
                      <div style={{ fontSize: 14, margin: "4px 0" }}>{d.new.stem_text}</div>
                      <div style={{ fontSize: 13 }}>{d.new.options.map((o) => `${o.label}. ${o.content_text}`).join("   ")}</div>
                      <div style={{ fontSize: 13, color: "#53627f" }}>
                        Đáp án nhận diện: {d.new.detected_answer ? `${d.new.detected_answer.label} (${d.new.detected_answer.source})` : "chưa có"}
                      </div>
                    </div>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: "#173a7a" }}>BẢN ĐANG CÓ TRONG KHO</div>
                      <div style={{ fontSize: 14, margin: "4px 0" }}>{d.existing.stem_text}</div>
                      <div style={{ fontSize: 13 }}>{d.existing.options.map((o) => `${o.label}. ${o.content_text}`).join("   ")}</div>
                      <div style={{ fontSize: 13, color: "#53627f" }}>
                        Từ đề: {d.existing.source_exam_title || "—"} · Trạng thái: {d.existing.status} · Đáp án hiện tại: {d.existing.correct_label || "chưa có"} ({d.existing.answer_source})
                      </div>
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 16, marginTop: 8, fontSize: 14 }}>
                    <label>
                      <input type="radio" name={`dec-${d.dedup_hash}`} checked={decisions[d.dedup_hash] === "keep"}
                        onChange={() => setDecisions({ ...decisions, [d.dedup_hash]: "keep" })} /> Giữ bản cũ
                    </label>
                    <label>
                      <input type="radio" name={`dec-${d.dedup_hash}`} checked={decisions[d.dedup_hash] === "overwrite"}
                        onChange={() => setDecisions({ ...decisions, [d.dedup_hash]: "overwrite" })} /> Ghi đè bằng bản mới
                    </label>
                  </div>
                </div>
              ))}
              <button style={{ padding: "9px 14px", background: "#12703a", color: "#fff", border: 0, borderRadius: 8, fontWeight: 700 }} onClick={() => runImport("decide", decisions)}>
                Áp dụng lựa chọn từng câu
              </button>
            </div>
          )}
          {nearDups.length > 0 && (
            <div style={{ background: "#fffbeb", border: "1px solid #f5d48b", borderRadius: 10, padding: 12, marginBottom: 12 }}>
              <b>⚠ Trùng ngữ nghĩa:</b> {nearDups.length} câu mới rất giống câu đã có trong kho (diễn đạt khác đôi chút) — vẫn được nạp, bạn kiểm tra lại ở màn Duyệt nếu cần.
            </div>
          )}
          {impStats && (
            <p style={{ marginTop: 12 }}>
              Kết quả nạp: <b>{impStats.total}</b> câu · có đáp án <b>{impStats.with_answer}</b> · chờ bổ sung đáp án{" "}
              <b>{impStats.needs_answer}</b> · trùng bỏ qua <b>{impStats.duplicates}</b> · ghi đè <b>{impStats.overwritten}</b> · lỗi <b>{impStats.failed}</b>.
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
            <button style={{ padding: "8px 14px", background: "#6d28d9", color: "#fff", border: 0, borderRadius: 8, fontWeight: 700 }} onClick={doSolveAI}>
              ✦ AI giải các câu chưa có đáp án
            </button>
            {solveMsg && <span style={{ fontSize: 13, color: "#53627f" }}>{solveMsg}</span>}
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
                {q.ai_solution && (
                  <div style={{ background: q.ai_solution.confidence >= 0.7 ? "#f5f0ff" : "#fef2f2", border: "1px solid #ddd0fa", borderRadius: 8, padding: 10, marginTop: 8, fontSize: 13 }}>
                    <b>✦ AI giải thích</b> <span style={{ color: "#53627f" }}>({q.ai_solution.model} · tin cậy {Math.round(q.ai_solution.confidence * 100)}%
                    {q.ai_solution.suggested_difficulty ? ` · gợi ý độ khó ${q.ai_solution.suggested_difficulty}` : ""})</span>
                    <div dangerouslySetInnerHTML={{ __html: q.ai_solution.explanation_html || "" }} />
                    {q.ai_solution.confidence < 0.7 && (
                      <div style={{ color: "#b42318", fontWeight: 650 }}>
                        AI chưa chắc chắn — nút Duyệt bị khoá cho đến khi bạn tự chọn đáp án đúng ở ô bên dưới.
                      </div>
                    )}
                  </div>
                )}
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
                  <button disabled={q.answer_source === "ai_solved" && (q.answer_confidence ?? 0) < 0.7 && !revAnswer[q.id]}
                    style={{ padding: "8px 14px", background: "#12703a", color: "#fff", border: 0, borderRadius: 8, fontWeight: 700,
                      opacity: q.answer_source === "ai_solved" && (q.answer_confidence ?? 0) < 0.7 && !revAnswer[q.id] ? 0.45 : 1 }}
                    onClick={() => doReview(q, "approve")}>Duyệt vào kho</button>
                  <button style={{ padding: "8px 14px", background: "#fff", color: "#b42318", border: "1px solid #e5b3ae", borderRadius: 8, fontWeight: 700 }} onClick={() => doReview(q, "reject")}>Loại bỏ</button>
                </div>
              </div>
            );
          })}
        </section>
      )}

      {tab === "builder" && (
        <section>
          <div style={{ ...box, marginBottom: 12 }}>
            <b>Mẫu đề của tôi</b>
            <span style={{ color: "#53627f", fontSize: 13 }}> — tự dựng mẫu theo đúng kho câu của bạn. Số liệu "kho có" là câu đã duyệt + có đáp án.</span>
            {templates.filter((tp) => !tp.is_system).map((tp) => (
              <div key={tp.id} style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8, fontSize: 14 }}>
                <span style={{ flex: 1 }}><b>{tp.name}</b> · {tp.total_questions} câu · {tp.duration_minutes} phút</span>
                <button style={btn} onClick={() => editTemplate(tp)}>Sửa</button>
                <button style={btn} onClick={() => removeTemplate(tp)}>Xoá</button>
              </div>
            ))}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
              <input placeholder="Tên mẫu, VD: Đề ôn Unit 3 — lớp 12" value={tplName} onChange={(e) => setTplName(e.target.value)} style={{ padding: 9, flex: 2 }} />
              <select value={tplGrade} onChange={(e) => setTplGrade(e.target.value)} style={{ padding: 9 }}>
                <option value="">Mọi khối</option><option value="10">Lớp 10</option><option value="11">Lớp 11</option><option value="12">Lớp 12</option>
              </select>
              <label style={{ fontSize: 13 }}>Thời gian (phút) <input type="number" min={1} value={tplDuration} onChange={(e) => setTplDuration(Number(e.target.value))} style={{ padding: 8, width: 70 }} /></label>
            </div>
            {tplSections.map((s, i) => (
              <div key={i} style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 8, background: "#f6f8fc", borderRadius: 8, padding: 8 }}>
                <input value={s.name} onChange={(e) => setSection(i, { name: e.target.value })} style={{ padding: 8, flex: 1 }} placeholder="Tên phần" />
                <select value={s.question_type} onChange={(e) => setSection(i, { question_type: e.target.value })} style={{ padding: 8 }}>
                  {qtypes.map((qt) => (<option key={qt.id} value={qt.code}>{qt.label}</option>))}
                </select>
                <span style={{ fontSize: 12, color: "#53627f" }}>
                  kho có: {avail[s.question_type] ? `${avail[s.question_type].standalone} độc lập · ${avail[s.question_type].with_passage} gắn đoạn` : "0 câu"}
                </span>
                <label style={{ fontSize: 13 }}>Số câu <input type="number" min={1} value={s.question_count} onChange={(e) => setSection(i, { question_count: Number(e.target.value) })} style={{ padding: 7, width: 60 }} /></label>
                <label style={{ fontSize: 13 }}><input type="checkbox" checked={s.with_passage} onChange={(e) => setSection(i, { with_passage: e.target.checked })} /> Gắn đoạn văn</label>
                <span style={{ fontSize: 12, color: "#53627f" }}>% NB/TH/VD/VDC:</span>
                {(["nb", "th", "vd", "vdc"] as const).map((k) => (
                  <input key={k} value={s[k]} onChange={(e) => setSection(i, { [k]: e.target.value } as Partial<TplSectionForm>)}
                    style={{ padding: 7, width: 44 }} placeholder={k.toUpperCase()} />
                ))}
                <button style={btn} onClick={() => setTplSections((prev) => prev.filter((_, j) => j !== i))}>✕</button>
              </div>
            ))}
            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
              <button style={btn} onClick={() => setTplSections((prev) => [...prev, { name: `Phần ${prev.length + 1}`, question_type: "vocabulary_mc", question_count: 5, with_passage: false, nb: "", th: "", vd: "", vdc: "" }])}>+ Thêm phần</button>
              <button style={{ padding: "8px 14px", background: "#12703a", color: "#fff", border: 0, borderRadius: 8, fontWeight: 700 }} onClick={saveTemplate}>
                {editTplId ? "Lưu thay đổi" : "Lưu mẫu mới"}
              </button>
              {editTplId && <button style={btn} onClick={() => setEditTplId(null)}>Huỷ sửa</button>}
              <span style={{ fontSize: 13, color: "#53627f", alignSelf: "center" }}>
                Tổng: {tplSections.reduce((a, s) => a + (s.question_count || 0), 0)} câu · Để trống % độ khó = lấy mọi mức
              </span>
            </div>
          </div>
          <div style={{ ...box, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <select value={genTplId} onChange={(e) => setGenTplId(e.target.value)} style={{ padding: 9, flex: 2 }}>
              {templates.map((tp) => (<option key={tp.id} value={tp.id}>{tp.name} — {tp.duration_minutes} phút</option>))}
            </select>
            <input placeholder="Tiêu đề đề (để trống = tên mẫu)" value={genTitle} onChange={(e) => setGenTitle(e.target.value)} style={{ padding: 9, flex: 2 }} />
            <select value={genVersions} onChange={(e) => setGenVersions(Number(e.target.value))} style={{ padding: 9 }}>
              <option value={1}>1 mã đề</option><option value={2}>2 mã đề</option><option value={4}>4 mã đề</option><option value={8}>8 mã đề</option>
            </select>
            <button style={{ padding: "9px 16px", background: "#173a7a", color: "#fff", border: 0, borderRadius: 8, fontWeight: 700 }} onClick={doGenerate}>
              🎲 Sinh đề từ kho đã duyệt
            </button>
          </div>
          {genShortfall && (
            <div style={{ background: "#fef2f2", border: "1px solid #f3b3ad", borderRadius: 10, padding: 12, whiteSpace: "pre-wrap" }}>
              <b>Chưa sinh được đề:</b> {genShortfall}
            </div>
          )}
          {genExam && (
            <div style={box}>
              <b>{genExam.title}</b> — {genExam.versions.length} mã đề · {genExam.versions[0]?.question_count} câu/mã
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 8, fontSize: 13 }}>
                {genExam.versions.map((v) => (
                  <span key={v.code}>Mã {v.code}: A×{v.answer_balance.A || 0} B×{v.answer_balance.B || 0} C×{v.answer_balance.C || 0} D×{v.answer_balance.D || 0}</span>
                ))}
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                <button style={btn} onClick={() => downloadDocx("student")}>⬇ Word — bản học sinh</button>
                <button style={btn} onClick={() => downloadDocx("teacher")}>⬇ Word — bản giáo viên (có đáp án)</button>
                <button style={btn} onClick={() => downloadDocx("matrix")}>⬇ Word — ma trận đề</button>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10, alignItems: "center" }}>
                <span>Xem trước mã:</span>
                <select value={prevCode} onChange={(e) => setPrevCode(e.target.value)} style={{ padding: 7 }}>
                  {genExam.versions.map((v) => (<option key={v.code} value={v.code}>{v.code}</option>))}
                </select>
                <label style={{ fontSize: 13 }}><input type="checkbox" checked={prevTeacher} onChange={(e) => setPrevTeacher(e.target.checked)} /> Hiện đáp án</label>
                <button style={btn} onClick={() => openPrint(prevTeacher)}>🖨 Mở bản in / PDF</button>
              </div>
              <div style={{ marginTop: 12, borderTop: "1px solid #e3e9f4", paddingTop: 10 }}>
                {(() => {
                  const ver = genExam.versions.find((v) => v.code === prevCode);
                  const seenPassage = new Set<string>();
                  return (ver?.items || []).map((it: any) => {
                    const showPassage = it.passage_id && !seenPassage.has(it.passage_id);
                    if (it.passage_id) seenPassage.add(it.passage_id);
                    return (
                      <div key={it.position} style={{ marginBottom: 10 }}>
                        {showPassage && it.passage && (<div style={{ fontStyle: "italic", margin: "8px 0 8px 16px" }} dangerouslySetInnerHTML={{ __html: it.passage.content_html }} />)}
                        <div><b>Câu {it.position}:</b> <span dangerouslySetInnerHTML={{ __html: it.stem_html }} /></div>
                        {it.options.map((o: any) => (
                          <div key={o.label} style={{ marginLeft: 22, ...(prevTeacher && o.label === it.correct_label ? { fontWeight: 700, textDecoration: "underline" } : {}) }}>
                            {o.label}. <span dangerouslySetInnerHTML={{ __html: o.html }} />
                          </div>
                        ))}
                      </div>
                    );
                  });
                })()}
              </div>
            </div>
          )}
        </section>
      )}
    </main>
  );
}
