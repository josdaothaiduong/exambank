"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearToken, downloadExamPackage, getToken, BulkApproveResult, ConflictResult, ExamTemplate, GeneratedExam, ImportResult, ImportStats, QuestionItem, QuestionPage, ReviewQueue, SolveResult, SourceExam, Tag, Workspace } from "../lib/api";

// ===== Ô chọn đề gốc dạng combobox (thay <select> thuần) =====
// Khi có nhiều đề / nhiều nhánh (lớp, loại đề, năm học), <select> thuần rất khó chọn:
// combobox này có ô tìm kiếm + gom nhóm theo lớp, đề mới nhất lên trước trong nhóm.
const EXAM_KIND_LABELS: Record<string, string> = {
  "15min": "15 phút", "45min": "45 phút", mid_term: "Giữa kỳ",
  final: "Cuối kỳ", graduation: "Tốt nghiệp", mock: "Thi thử",
};
function examKindLabel(kind: string | null): string | null {
  if (!kind) return null;
  return EXAM_KIND_LABELS[kind] || kind;
}

function ExamPicker({ exams, value, onChange, dark = false }: {
  exams: SourceExam[]; value: string; onChange: (id: string) => void; dark?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const selected = exams.find((e) => e.id === value) || null;

  // Đóng khi bấm ra ngoài hoặc nhấn Esc
  useEffect(() => {
    if (!open) return;
    const onDoc = (ev: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(ev.target as Node)) setOpen(false);
    };
    const onKey = (ev: KeyboardEvent) => { if (ev.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open ]);

  const q = query.trim().toLowerCase();
  const matches = (e: SourceExam) => !q
    || e.title.toLowerCase().includes(q)
    || (examKindLabel(e.exam_kind) || "").toLowerCase().includes(q)
    || (e.exam_kind || "").toLowerCase().includes(q)
    || (e.school_year || "").toLowerCase().includes(q);
  const byNewest = (a: SourceExam, b: SourceExam) => (b.created_at || "").localeCompare(a.created_at || "");
  const groups: { label: string; items: SourceExam[] }[] = [];
  for (const g of [10, 11, 12]) {
    const items = exams.filter((e) => e.grade === g && matches(e)).sort(byNewest);
    if (items.length) groups.push({ label: `Lớp ${g}`, items });
  }
  const ungraded = exams.filter((e) => e.grade !== 10 && e.grade !== 11 && e.grade !== 12 && matches(e)).sort(byNewest);
  if (ungraded.length) groups.push({ label: "Chưa xếp lớp", items: ungraded });
  const shownCount = groups.reduce((n, g) => n + g.items.length, 0);

  return (
    <div ref={rootRef} className={`eb-picker${dark ? " eb-picker-dark" : ""}`}>
      <button type="button" className="eb-picker-btn" aria-haspopup="listbox" aria-expanded={open}
        onClick={() => setOpen((o) => !o)}>
        {selected ? (
          <>
            <span className="eb-picker-title">{selected.title}</span>
            {selected.grade ? <span className="eb-picker-grade">Lớp {selected.grade}</span> : null}
          </>
        ) : (
          <span className="eb-picker-placeholder">— Chọn đề gốc —</span>
        )}
        <span className={`eb-picker-caret${open ? " open" : ""}`}>▾</span>
      </button>
      {open && (
        <div className="eb-picker-panel" role="listbox" aria-label="Danh sách đề gốc">
          <div className="eb-picker-search">
            <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="🔎 Tìm theo tên đề, loại đề, năm học…" />
          </div>
          <div className="eb-picker-list">
            {exams.length === 0 && <div className="eb-picker-empty">Chưa có đề gốc nào trong workspace này.</div>}
            {exams.length > 0 && shownCount === 0 && (
              <div className="eb-picker-empty">Không tìm thấy đề khớp “{query}” — thử từ khoá ngắn hơn.</div>
            )}
            {groups.map((g) => (
              <div key={g.label}>
                <div className="eb-picker-group">{g.label}</div>
                {g.items.map((e) => {
                  const isSel = e.id === value;
                  const meta = [examKindLabel(e.exam_kind), e.school_year].filter(Boolean).join(" · ");
                  return (
                    <button key={e.id} type="button" role="option" aria-selected={isSel}
                      className={`eb-picker-item${isSel ? " sel" : ""}`}
                      onClick={() => { onChange(e.id); setOpen(false); setQuery(""); }}>
                      <span className="eb-picker-item-main">
                        <span className="eb-picker-item-title">{e.title}</span>
                        {meta && <span className="eb-picker-item-meta">{meta}</span>}
                      </span>
                      {isSel && <span className="eb-picker-check">✓</span>}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

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
  // Câu nào GV đã TỰ tay đổi ô Độ khó thì ghi vào đây: hiệu ứng tự điền từ
  // ai_difficulty (dưới) không bao giờ ghi đè lựa chọn của GV trong phiên.
  const [revDiffManual, setRevDiffManual] = useState<Record<string, boolean>>({});
  const [revUnit, setRevUnit] = useState<Record<string, string>>({});
  const [revAnswer, setRevAnswer] = useState<Record<string, string>>({});
  const [activeQ, setActiveQ] = useState("");

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
  const [solveInfo, setSolveInfo] = useState("");
  const [aiSolving, setAiSolving] = useState(false);
  const aiPollGenRef = useRef(0);
  // Duyệt hàng loạt các câu đủ tin cậy (panel xác nhận nội tuyến ở tab Duyệt)
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkUnitId, setBulkUnitId] = useState("");
  // Mặc định BẬT theo yêu cầu GV (2026-11-07): duyệt hàng loạt dùng luôn độ
  // khó AI đề xuất cho các câu có gợi ý, GV đỡ phải chọn tay từng câu.
  const [bulkUseAiDiff, setBulkUseAiDiff] = useState(true);
  // Mặc định TẮT: chấp nhận cả đáp án AI tin cậy < 70% khi duyệt hàng loạt —
  // quyết định thay nhiều cú click chọn tay, GV phải chủ động bật kèm cảnh báo.
  const [bulkAcceptLowAi, setBulkAcceptLowAi] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkSummary, setBulkSummary] = useState<{ approved: number; skipped: { question_id: string; reason: string }[] } | null>(null);
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
  // Chữ ký "đã giải" của 1 câu AI trong hàng chờ — dùng để nhận biết lượt
  // giải LẠI đã cập nhật câu đó chưa khi poll đường async.
  const aiSig = (it: QuestionItem) => (it.ai_solution
    ? `${it.ai_solution.confidence}|${it.ai_solution.explanation_html || ""}` : "");

  async function doSolveAI(kind: "solve" | "resolve" = "solve") {
    if (!impExamId) { setError("Hãy chọn đề gốc trước"); return; }
    if (aiSolving) return;
    setSolveInfo("");
    setBulkSummary(null);
    setSolveMsg(kind === "resolve" ? "Đang giao AI giải lại..." : "Đang giao AI giải...");
    // Giải lại: chụp chữ ký ai_solution hiện tại của các câu AI — poll async sẽ
    // đếm số câu CHƯA đổi chữ ký để biết khi nào lượt giải mới đã chạm tới.
    const sigBefore = new Map<string, string>();
    if (kind === "resolve") {
      try {
        const fresh = await api<ReviewQueue>(`/api/v1/source-exams/${impExamId}/review-queue`);
        fresh.items.filter((it) => it.answer_source === "ai_solved")
          .forEach((it) => sigBefore.set(it.id, aiSig(it)));
      } catch { /* không chụp được thì poll theo thời gian tối đa như cũ */ }
    }
    try {
      const r = await api<SolveResult>(`/api/v1/source-exams/${impExamId}/${kind === "resolve" ? "resolve-ai" : "solve-ai"}`, { method: "POST" });
      if (r.mode === "async") {
        // Chạy nền (Docker, AI_ASYNC=1): endpoint chỉ trả task_id — poll hàng chờ
        // mỗi 4 giây cho tới khi không còn câu nào đang chờ lượt giải này
        // (tối đa 45 lần). "solve": câu needs_answer về 0; "resolve": mọi câu
        // AI trong ảnh chụp ban đầu đều đã đổi chữ ký ai_solution.
        setAiSolving(true);
        setSolveMsg(`Đã giao AI ${kind === "resolve" ? "giải lại" : "giải"} ${r.total} câu — đang chạy nền, kết quả sẽ tự xuất hiện bên dưới, đừng tắt trang này.`);
        const gen = ++aiPollGenRef.current;
        let remaining = -1;
        for (let i = 0; i < 45; i++) {
          await new Promise((res) => setTimeout(res, 4000));
          if (aiPollGenRef.current !== gen) return; // đã có lượt giao mới / đã huỷ
          loadQueue(impExamId);
          try {
            const fresh = await api<ReviewQueue>(`/api/v1/source-exams/${impExamId}/review-queue`);
            remaining = kind === "resolve"
              ? fresh.items.filter((it) => sigBefore.has(it.id) && aiSig(it) === sigBefore.get(it.id)).length
              : fresh.items.filter((it) => it.status === "needs_answer").length;
          } catch { remaining = -1; }
          if (remaining === 0) break;
        }
        if (aiPollGenRef.current !== gen) return;
        setAiSolving(false);
        if (remaining === 0) {
          setSolveMsg(kind === "resolve"
            ? "AI đã giải lại xong — đáp án, độ tin cậy và gợi ý độ khó đã cập nhật theo lượt giải mới, hãy kiểm tra rồi duyệt."
            : "AI đã giải xong — hãy kiểm tra từng câu rồi duyệt (câu nào AI chưa chắc dưới 70% sẽ bị chặn duyệt mù như quy định).");
        } else {
          setSolveMsg("AI vẫn đang chạy nền lâu hơn dự kiến — tải lại trang sau ít phút để xem kết quả.");
        }
        loadQueue(impExamId);
      } else {
        // Backend báo fallback=true: hàng đợi nền chưa sẵn sàng nên đã giải trực tiếp
        // ngay trong request — đây là thông tin (info), không phải lỗi.
        if (r.fallback) setSolveInfo("Đã giải trực tiếp vì hàng đợi nền chưa sẵn sàng.");
        setSolveMsg(`AI (${r.model}) đã ${kind === "resolve" ? "giải lại" : "giải"} ${r.solved ?? 0}/${r.total} câu · ${r.low_confidence ?? 0} câu độ tin cậy thấp cần kiểm tra kỹ · chi phí ước tính $${(r.cost_usd ?? 0).toFixed(4)}.`);
        loadQueue(impExamId);
      }
    } catch (err: any) { setError(err.message); setSolveMsg(""); setAiSolving(false); }
  }

  function doResolveAI() {
    if (aiSolving) return;
    const ok = window.confirm(
      "AI sẽ GIẢI LẠI các câu do AI đã giải (chưa duyệt): đáp án AI cũ sẽ bị thay bằng kết quả giải mới.\n\n" +
      "Đáp án từ tô đỏ / highlight / bảng đáp án, câu bạn đã tự chọn đáp án và câu đã duyệt KHÔNG bị ảnh hưởng.\n\nTiếp tục?");
    if (ok) doSolveAI("resolve");
  }

  // Tiêu chí "đủ tin cậy" để duyệt hàng loạt — KHỚP ĐÚNG tiêu chí server
  // (approve-ready): có đáp án đã đặt VÀ (nguồn nhận diện/giáo viên tự chọn,
  // HOẶC đáp án AI với độ tin cậy >= 70%). Chỉ để hiển thị số N trên nút;
  // server tự tính lại, client không gửi danh sách câu.
  const TRUSTED_SOURCES = ["red_text", "highlight", "bold_underline", "marker_star", "answer_key_table", "teacher_manual"];
  const bulkEligible = (q: QuestionItem): boolean => {
    if (!q.correct_option_id) return false;
    if (q.answer_source === "ai_solved") return (q.ai_solution?.confidence ?? q.answer_confidence ?? 0) >= 0.7;
    return TRUSTED_SOURCES.includes(q.answer_source);
  };
  // Câu AI đã có đáp án nhưng tin cậy < 70%: bình thường bị duyệt hàng loạt bỏ
  // qua; CHỈ được duyệt khi GV bật tuỳ chọn accept_low_confidence_ai ở panel.
  const bulkLowAi = (q: QuestionItem): boolean =>
    !!q.correct_option_id && q.answer_source === "ai_solved"
    && (q.ai_solution?.confidence ?? q.answer_confidence ?? 0) < 0.7;

  async function doBulkApprove() {
    if (!impExamId || bulkBusy) return;
    setBulkBusy(true);
    try {
      const r = await api<BulkApproveResult>(`/api/v1/source-exams/${impExamId}/approve-ready`, {
        method: "POST",
        body: JSON.stringify({ unit_tag_id: bulkUnitId || null, use_ai_difficulty: bulkUseAiDiff, accept_low_confidence_ai: bulkAcceptLowAi }),
      });
      setBulkSummary({ approved: r.approved_count, skipped: r.skipped });
      setBulkOpen(false);
      loadQueue(impExamId);
    } catch (err: any) { setError(err.message); }
    finally { setBulkBusy(false); }
  }

  const loadQueue = useCallback((examId: string) => {
    if (!examId) { setQueue(null); return; }
    api<ReviewQueue>(`/api/v1/source-exams/${examId}/review-queue`).then(setQueue).catch((e) => setError(e.message));
  }, []);
  useEffect(() => { if (tab === "review" && impExamId) loadQueue(impExamId); }, [tab, impExamId, loadQueue]);

  // Độ khó AI TỰ ĐIỀN SẴN vào ô Độ khó của thẻ (yêu cầu GV 2026-11-07 — bỏ
  // bước bấm chip "đề xuất" thừa): mỗi khi hàng chờ (tải lại), câu nào có
  // ai_difficulty thì revDiff được khởi tạo/cập nhật theo gợi ý đó, TRỪ câu
  // GV đã tự tay đổi trong phiên này (revDiffManual) — không ghi đè GV.
  // GV vẫn sửa tự do bằng dropdown như thường.
  useEffect(() => {
    if (!queue) return;
    setRevDiff((prev) => {
      let next = prev;
      for (const q of queue.items) {
        if (!q.ai_difficulty || revDiffManual[q.id]) continue;
        if (next[q.id] !== q.ai_difficulty) {
          if (next === prev) next = { ...prev };
          next[q.id] = q.ai_difficulty;
        }
      }
      return next;
    });
  }, [queue, revDiffManual]);

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

  const box: React.CSSProperties = { border: "1px solid #E3E8F4", borderRadius: 16, padding: 18, marginBottom: 12, background: "#fff", boxShadow: "0 1px 2px rgb(16 27 60 / .05), 0 10px 24px -14px rgb(16 27 60 / .14)" };
  const btn: React.CSSProperties = { padding: "8px 14px", borderRadius: 12, border: "1px solid #C9D4EE", background: "#fff", cursor: "pointer", fontWeight: 600 };

  // ===== Tab Duyệt: gom nhóm theo đoạn văn, tô sáng chỗ trống đang xem, thẻ câu dạng lưới chọn đáp án =====
  const blankNoOf = (q: QuestionItem): number | null => {
    const m = /^Chỗ trống số (\d+)/.exec((q.stem_text || "").trim());
    if (m) return parseInt(m[1], 10);
    return q.order_in_source ?? null;
  };

  const highlightPassage = (src: string, isHtml: boolean, active: number | null, blanks: Set<number>): string => {
    let s = src;
    if (!isHtml) s = s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return s.replace(/\((\d+)\)/g, (whole, d: string) => {
      const n = parseInt(d, 10);
      if (active != null && n === active) return `<span style="background:#F59E0B;color:#451A03;border-radius:6px;padding:0 6px;font-weight:800">(${n})</span>`;
      if (blanks.has(n)) return `<span style="background:#FEF3C7;border-radius:6px;padding:0 6px;font-weight:650">(${n})</span>`;
      return whole;
    });
  };

  const reviewCard = (q: QuestionItem, inPassage: boolean, isActive: boolean) => {
    const correctLabel = q.options.find((o) => o.id === q.correct_option_id)?.label;
    const selectedLabel = revAnswer[q.id] || correctLabel;
    const blankNo = blankNoOf(q);
    const isBlankStem = /^Chỗ trống số \d+/.test((q.stem_text || "").trim());
    const aiLocked = q.answer_source === "ai_solved" && (q.answer_confidence ?? 0) < 0.7 && !revAnswer[q.id];
    // Ô Độ khó đang mang giá trị do AI điền sẵn (chưa bị GV sửa tay trong phiên)
    const diffByAi = !!q.ai_difficulty && !revDiffManual[q.id] && revDiff[q.id] === q.ai_difficulty;
    return (
      <div key={q.id} onClick={() => setActiveQ(q.id)}
        style={{ ...box, cursor: "pointer", ...(isActive ? { border: "2px solid #F59E0B", boxShadow: "0 2px 4px rgb(16 27 60 / .08), 0 16px 32px -12px rgb(245 158 11 / .45)" } : {}) }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
          <span style={{ background: "#101B3C", color: "#fff", fontWeight: 800, fontSize: 13, padding: "5px 11px", borderRadius: 999 }}>
            {inPassage && blankNo != null ? `Chỗ trống ${blankNo}` : q.order_in_source != null ? `Câu số ${q.order_in_source} trong đề gốc` : "Câu hỏi"}
          </span>
          {q.status === "needs_answer" ? (
            <span style={{ background: "#FFFBEB", color: "#B45309", border: "1px solid #FDE68A", fontWeight: 700, fontSize: 12.5, padding: "4px 10px", borderRadius: 999 }}>⏳ Chưa có đáp án</span>
          ) : q.status === "pending_review" ? (
            <span style={{ background: "#EAF0FF", color: "#2547D0", border: "1px solid #C7D7FF", fontWeight: 700, fontSize: 12.5, padding: "4px 10px", borderRadius: 999 }}>Chờ duyệt</span>
          ) : (
            <span style={{ background: "#F4F6FB", color: "#4A5578", border: "1px solid #E3E8F4", fontWeight: 700, fontSize: 12.5, padding: "4px 10px", borderRadius: 999 }}>{q.status}</span>
          )}
        </div>
        {(!inPassage || !isBlankStem) && (
          <div style={{ fontWeight: 650 }} dangerouslySetInnerHTML={{ __html: q.stem_html || q.stem_text }} />
        )}
        <div className="eb-opt-grid">
          {q.options.map((o) => {
            const selected = o.label === selectedLabel;
            const isDetected = o.label === correctLabel;
            return (
              <button key={o.id} type="button" className="eb-opt"
                onClick={(e) => { e.stopPropagation(); setActiveQ(q.id); setRevAnswer({ ...revAnswer, [q.id]: o.label }); }}
                style={{ border: selected ? "2px solid #15803D" : "1.5px solid #E3E8F4", background: selected ? "#F0FDF4" : "#fff" }}>
                <span className="eb-opt-label" style={{ background: selected ? "#15803D" : "#EAF0FF", color: selected ? "#fff" : "#101B3C" }}>{o.label}</span>
                <span style={{ flex: 1 }}>
                  <span dangerouslySetInnerHTML={{ __html: o.content_html || o.content_text }} />
                  {isDetected && <span style={{ display: "inline-block", marginLeft: 8, fontSize: 12, fontWeight: 700, color: "#15803D", background: "#F0FDF4", border: "1px solid #BBF7D0", padding: "1px 7px", borderRadius: 999 }}>✓ hệ thống nhận diện</span>}
                </span>
                {selected && <span style={{ color: "#15803D", fontWeight: 900 }}>✓</span>}
              </button>
            );
          })}
        </div>
        <div style={{ color: "#4A5578", fontSize: 13, marginTop: 6 }}>
          Nguồn đáp án: {q.answer_source}
          {q.answer_confidence != null ? ` · độ tin cậy ${Math.round(q.answer_confidence * 100)}%` : ""}
          {q.order_in_source != null ? ` · Câu số ${q.order_in_source} trong đề gốc` : ""}
        </div>
        {q.ai_solution && (
          <div style={{ background: q.ai_solution.confidence >= 0.7 ? "#f5f0ff" : "#fef2f2", border: "1px solid #DDD0FA", borderRadius: 12, padding: 10, marginTop: 8, fontSize: 13 }}>
            <b>✦ AI giải thích</b> <span style={{ color: "#4A5578" }}>({q.ai_solution.model} · tin cậy {Math.round(q.ai_solution.confidence * 100)}%
            {q.ai_solution.suggested_difficulty ? ` · gợi ý độ khó ${q.ai_solution.suggested_difficulty}` : ""})</span>
            <div dangerouslySetInnerHTML={{ __html: q.ai_solution.explanation_html || "" }} />
            {q.ai_solution.confidence < 0.7 ? (
              <div style={{ color: "#B91C1C", fontWeight: 650 }}>
                AI chưa chắc chắn — nút Duyệt bị khoá cho đến khi bạn tự chọn đáp án đúng ở lưới phương án phía trên.
              </div>
            ) : (
              <div style={{ color: "#2547D0", fontWeight: 600 }}>
                AI đã chọn đáp án này (tin cậy {Math.round(q.ai_solution.confidence * 100)}%) — bấm Duyệt vào kho để xác nhận, hoặc bấm phương án khác nếu không đồng ý.
              </div>
            )}
          </div>
        )}
        {q.status === "needs_answer" && !selectedLabel && (
          <div style={{ marginTop: 10, fontSize: 13.5, color: "#92400E", background: "#FFFBEB", border: "1px dashed #F59E0B", borderRadius: 10, padding: "8px 12px" }}>
            💡 Hãy chọn 1 phương án đúng ở trên, hoặc bấm AI giải các câu chưa có đáp án ở đầu trang.
          </div>
        )}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10, alignItems: "center" }} onClick={(e) => e.stopPropagation()}>
          {diffByAi && (
            <span className="eb-ai-diff eb-ai-diff-tag"
              title="Ô Độ khó đã được AI điền sẵn theo gợi ý của lần giải gần nhất — GV cứ đổi ở ô Độ khó bên cạnh nếu thấy chưa đúng">
              ✦ AI đã điền: {revDiff[q.id]} — đổi nếu cần
            </span>
          )}
          <select value={revDiff[q.id] || ""} onChange={(e) => { setRevDiff({ ...revDiff, [q.id]: e.target.value }); setRevDiffManual({ ...revDiffManual, [q.id]: true }); }} style={{ padding: 8 }}>
            <option value="">— Độ khó —</option><option>NB</option><option>TH</option><option>VD</option><option>VDC</option>
          </select>
          <select value={revUnit[q.id] || ""} onChange={(e) => setRevUnit({ ...revUnit, [q.id]: e.target.value })} style={{ padding: 8 }}>
            <option value="">— Unit —</option>
            {units.map((u) => (<option key={u.id} value={u.code}>{u.label}</option>))}
          </select>
          <span style={{ flex: 1 }} />
          <button disabled={aiLocked}
            style={{ padding: "8px 14px", background: "#15803D", color: "#fff", border: 0, borderRadius: 12, fontWeight: 700, opacity: aiLocked ? 0.45 : 1 }}
            onClick={() => doReview(q, "approve")}>Duyệt vào kho</button>
          <button style={{ padding: "8px 14px", background: "#fff", color: "#B91C1C", border: "1px solid #F0B8B2", borderRadius: 12, fontWeight: 700 }} onClick={() => doReview(q, "reject")}>Loại bỏ</button>
        </div>
      </div>
    );
  };

  return (
    <div className="eb-shell">
      <aside className="eb-side">
        <h1 className="eb-logo"><span className="eb-mark">📚</span> ExamBank AI</h1>
        <div className="eb-side-label">Giảng dạy</div>
        <nav className="eb-nav">
          <button className={tab === "exams" ? "eb-on" : ""} onClick={() => setTab("exams")}>📖 Đề gốc</button>
          <button className={tab === "bank" ? "eb-on" : ""} onClick={() => setTab("bank")}>🗂 Kho câu hỏi</button>
          <button className={tab === "import" ? "eb-on" : ""} onClick={() => setTab("import")}>📥 Nhập đề</button>
          <button className={tab === "review" ? "eb-on" : ""} onClick={() => setTab("review")}>✅ Duyệt câu hỏi</button>
          <button className={tab === "builder" ? "eb-on" : ""} onClick={() => setTab("builder")}>🧩 Tạo đề</button>
        </nav>
        <div className="eb-side-foot">
          <label>
            Workspace
            <select value={wsId} onChange={(e) => setWsId(e.target.value)}>
              {workspaces.map((w) => (<option key={w.id} value={w.id}>{w.name}</option>))}
            </select>
          </label>
          <button className="eb-logout" onClick={() => { clearToken(); router.push("/login"); }}>Đăng xuất</button>
        </div>
      </aside>

      <main className="eb-main">
      {error && <p style={{ color: "#B91C1C", background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 12, padding: "10px 14px" }}>{error}</p>}

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
            <button style={{ padding: "9px 16px", background: "#2547D0", color: "#fff", border: 0, borderRadius: 12, fontWeight: 700 }}>+ Tạo đề gốc</button>
          </form>
          {exams.length === 0 && <p>Chưa có đề gốc nào trong workspace này.</p>}
          {exams.map((e) => (
            <div key={e.id} style={{ ...box, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
              <span><b>{e.title}</b> — Lớp {e.grade} · {e.exam_kind}</span>
              <button style={btn} onClick={() => downloadExamPackage(e.id).catch((err) => setError(err.message))}>Xuất gói đề</button>
            </div>
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
              <div style={{ color: "#4A5578", fontSize: 13, marginTop: 4 }}>
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
            <ExamPicker exams={exams} value={impExamId} onChange={setImpExamId} />
            <label style={{ ...btn, display: "inline-block" }}>
              Hoặc tải file .docx
              <input type="file" accept=".docx" style={{ display: "none" }}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) doImportDocx(f); e.target.value = ""; }} />
            </label>
          </div>
          <p style={{ color: "#4A5578", fontSize: 13 }}>
            Dán đề từ Word/PDF vào ô dưới (giữ nguyên đáp án tô đỏ hoặc highlight), mỗi câu bắt đầu bằng
            "Question 1:" và các phương án A. B. C. D. — hệ thống tự tách câu và nhận đáp án, không chắc thì để trống chờ duyệt.
          </p>
          <div ref={pasteRef} contentEditable suppressContentEditableWarning
            style={{ border: "1.5px dashed #9DB4E8", borderRadius: 16, padding: 14, minHeight: 130, background: "#F7FAFF" }} />
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button style={{ padding: "9px 16px", background: "#2547D0", color: "#fff", border: 0, borderRadius: 12, fontWeight: 700 }} onClick={doImportPaste}>
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
                <button style={{ padding: "9px 14px", background: "#b45309", color: "#fff", border: 0, borderRadius: 12, fontWeight: 700 }} onClick={() => runImport("overwrite")}>
                  Ghi đè tất cả câu trùng bằng bản mới
                </button>
                <button style={{ padding: "9px 14px", background: "#2547D0", color: "#fff", border: 0, borderRadius: 12, fontWeight: 700 }} onClick={() => runImport("keep_old")}>
                  Giữ bản cũ — chỉ nạp {conflict.new_count} câu mới
                </button>
                <button style={btn} onClick={() => setConflict(null)}>Huỷ — không nạp gì cả</button>
              </div>
              <p style={{ fontSize: 13, color: "#4A5578", margin: "4px 0 10px" }}>
                Hoặc xem từng câu bên dưới, chọn riêng cho từng câu rồi bấm "Áp dụng lựa chọn từng câu". Lưu ý: câu đã duyệt mà bị ghi đè sẽ quay về trạng thái chờ duyệt.
              </p>
              {conflict.duplicates.map((d) => (
                <div key={d.dedup_hash} style={{ border: "1px solid #e5d9b8", borderRadius: 10, padding: 12, marginBottom: 10, background: "#fff" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: "#b45309" }}>BẢN MỚI NẠP — Câu {d.number}</div>
                      <div style={{ fontSize: 14, margin: "4px 0" }}>{d.new.stem_text}</div>
                      <div style={{ fontSize: 13 }}>{d.new.options.map((o) => `${o.label}. ${o.content_text}`).join("   ")}</div>
                      <div style={{ fontSize: 13, color: "#4A5578" }}>
                        Đáp án nhận diện: {d.new.detected_answer ? `${d.new.detected_answer.label} (${d.new.detected_answer.source})` : "chưa có"}
                      </div>
                    </div>
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: "#2547D0" }}>BẢN ĐANG CÓ TRONG KHO</div>
                      <div style={{ fontSize: 14, margin: "4px 0" }}>{d.existing.stem_text}</div>
                      <div style={{ fontSize: 13 }}>{d.existing.options.map((o) => `${o.label}. ${o.content_text}`).join("   ")}</div>
                      <div style={{ fontSize: 13, color: "#4A5578" }}>
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
              <button style={{ padding: "9px 14px", background: "#15803D", color: "#fff", border: 0, borderRadius: 12, fontWeight: 700 }} onClick={() => runImport("decide", decisions)}>
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
          {(() => {
            const items = queue?.items || [];
            const readyCount = items.filter((q) => q.correct_option_id || revAnswer[q.id]).length;
            const noAnswerCount = items.filter((q) => q.status === "needs_answer" && !q.correct_option_id && !revAnswer[q.id]).length;
            const aiSolvedCount = items.filter((q) => q.answer_source === "ai_solved").length;
            const bulkCount = items.filter(bulkEligible).length;
            const bulkLowAiCount = items.filter(bulkLowAi).length;
            const bulkTotal = bulkCount + (bulkAcceptLowAi ? bulkLowAiCount : 0);
            // Gom nhóm: các câu LIÊN TIẾP có cùng passage_text thành 1 nhóm đoạn văn.
            type RevGroup = { key: string; passage: QuestionItem | null; items: QuestionItem[] };
            const groups: RevGroup[] = [];
            items.forEach((q) => {
              const p = (q.passage_text || "").trim();
              const last = groups[groups.length - 1];
              if (p && last && last.passage && (last.passage.passage_text || "").trim() === p) last.items.push(q);
              else groups.push({ key: q.id, passage: p ? q : null, items: [q] });
            });
            return (
              <>
                <div style={{ ...box, background: "linear-gradient(135deg, #101B3C 0%, #1B37A8 100%)", color: "#fff", border: "0" }}>
                  <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{ fontWeight: 700 }}>Đề gốc:</span>
                    <ExamPicker dark exams={exams} value={impExamId} onChange={setImpExamId} />
                    <span style={{ background: "rgb(255 255 255 / .14)", border: "1px solid rgb(255 255 255 / .25)", padding: "6px 12px", borderRadius: 999, fontSize: 13.5 }}>
                      Đang chờ duyệt: <b className="numeric">{queue?.total ?? 0}</b> câu
                    </span>
                    <span style={{ background: "#F0FDF4", color: "#15803D", padding: "6px 12px", borderRadius: 999, fontSize: 13.5, fontWeight: 650 }}>
                      ✓ Đã sẵn đáp án: <b className="numeric">{readyCount}</b>
                    </span>
                    <span style={{ background: "#FFFBEB", color: "#B45309", padding: "6px 12px", borderRadius: 999, fontSize: 13.5, fontWeight: 650 }}>
                      ⏳ Chưa có đáp án: <b className="numeric">{noAnswerCount}</b>
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginTop: 12 }}>
                    <button disabled={aiSolving}
                      style={{ padding: "9px 16px", background: aiSolving ? "#7C6AAE" : "#6d28d9", color: "#fff", border: 0, borderRadius: 12, fontWeight: 700, opacity: aiSolving ? 0.75 : 1 }}
                      onClick={() => doSolveAI("solve")}>
                      {aiSolving ? "✦ AI đang giải…" : "✦ AI giải các câu chưa có đáp án"}
                    </button>
                    {aiSolvedCount > 0 && (
                      <button disabled={aiSolving}
                        title="Giải lại các câu do AI đã giải nhưng chưa duyệt — dùng khi đã cắm key AI thật để thay kết quả của bộ giải demo"
                        style={{ padding: "9px 16px", background: "rgb(255 255 255 / .12)", color: "#fff", border: "1px solid rgb(255 255 255 / .45)", borderRadius: 12, fontWeight: 700, opacity: aiSolving ? 0.6 : 1 }}
                        onClick={doResolveAI}>
                        ↻ AI giải lại các câu AI đã giải ({aiSolvedCount})
                      </button>
                    )}
                    {(bulkCount > 0 || bulkLowAiCount > 0) && (
                      <button disabled={bulkBusy}
                        title="Duyệt một lượt các câu có đáp án đáng tin cậy — câu AI dưới 70% tin cậy chỉ được duyệt khi bạn chủ động bật tuỳ chọn trong panel"
                        style={{ padding: "9px 16px", background: "#15803D", color: "#fff", border: 0, borderRadius: 12, fontWeight: 700, opacity: bulkBusy ? 0.7 : 1 }}
                        onClick={() => { setBulkSummary(null); setBulkOpen((o) => !o); }}>
                        ✓ Duyệt hàng loạt: {bulkCount} câu đủ tin cậy{bulkLowAiCount > 0 ? ` · ${bulkLowAiCount} câu AI dưới 70%` : ""}
                      </button>
                    )}
                    {solveMsg && <span style={{ fontSize: 13.5, color: "#DCE4FF" }}>{solveMsg}</span>}
                  </div>
                  {solveInfo && (
                    <div style={{ marginTop: 10, background: "#DBEAFE", color: "#1E3A8A", border: "1px solid #93C5FD", borderRadius: 10, padding: "8px 12px", fontSize: 13.5, fontWeight: 600 }}>
                      ℹ️ {solveInfo}
                    </div>
                  )}
                  {bulkOpen && (
                    <div style={{ marginTop: 12, background: "#fff", color: "#101B3C", borderRadius: 12, padding: 14 }}>
                      <div style={{ fontWeight: 750, marginBottom: 4 }}>
                        Duyệt hàng loạt {bulkTotal} câu
                        <span style={{ fontWeight: 600, color: "#4A5578", fontSize: 13 }}>
                          {" "}({bulkCount} câu đủ tin cậy{bulkLowAiCount > 0 ? ` · ${bulkLowAiCount} câu AI tin cậy dưới 70%${bulkAcceptLowAi ? " — ĐÃ gồm nhờ tuỳ chọn bên dưới" : " — đang bị bỏ qua"}` : ""})
                        </span>
                      </div>
                      <div style={{ fontSize: 13, color: "#4A5578", marginBottom: 10 }}>
                        Câu đủ tin cậy: đáp án từ tô đỏ / highlight / bảng đáp án / bạn tự chọn, hoặc đáp án AI có
                        độ tin cậy từ 70% trở lên. Câu AI chưa chắc chắn (dưới 70%) mặc định bị bỏ qua — chỉ được
                        duyệt khi bạn chủ động bật tuỳ chọn chấp nhận bên dưới.
                      </div>
                      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
                        <label style={{ fontSize: 13.5, fontWeight: 600 }}>
                          Unit chung:
                          <select value={bulkUnitId} onChange={(e) => setBulkUnitId(e.target.value)} style={{ padding: 8, marginLeft: 6 }}>
                            <option value="">— Không gán —</option>
                            {units.map((u) => (<option key={u.id} value={u.id}>{u.label}</option>))}
                          </select>
                        </label>
                        <label style={{ fontSize: 13.5, display: "flex", gap: 6, alignItems: "center" }} title="Câu nào có gợi ý độ khó của AI thì gán mức đó; câu không có gợi ý vẫn để trống">
                          <input type="checkbox" checked={bulkUseAiDiff} onChange={(e) => setBulkUseAiDiff(e.target.checked)} />
                          Dùng độ khó AI đề xuất cho các câu
                        </label>
                        <span style={{ flex: 1 }} />
                        <button disabled={bulkBusy || bulkTotal === 0}
                          style={{ padding: "8px 14px", background: "#15803D", color: "#fff", border: 0, borderRadius: 12, fontWeight: 700, opacity: bulkBusy || bulkTotal === 0 ? 0.7 : 1 }}
                          onClick={doBulkApprove}>
                          {bulkBusy ? "Đang duyệt…" : `Duyệt ${bulkTotal} câu`}
                        </button>
                        <button disabled={bulkBusy} style={btn} onClick={() => setBulkOpen(false)}>Huỷ</button>
                      </div>
                      {bulkLowAiCount > 0 && (
                        <label style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13.5, background: "#FFFBEB", border: "1px solid #FDE68A", borderRadius: 10, padding: "10px 12px", cursor: "pointer" }}>
                          <input type="checkbox" checked={bulkAcceptLowAi} onChange={(e) => setBulkAcceptLowAi(e.target.checked)} style={{ marginTop: 2 }} />
                          <span>
                            <b>Chấp nhận cả đáp án AI độ tin cậy dưới 70%</b> (kèm các câu demo nếu chưa giải lại) — tôi đã xem qua danh sách và chịu trách nhiệm.
                            <span style={{ display: "block", color: "#92400E", fontSize: 12.5, marginTop: 2 }}>
                              Khi bật, {bulkLowAiCount} câu AI tin cậy thấp cũng được duyệt luôn trong mẻ này, thay cho việc bạn phải tự chọn đáp án từng câu. Đáp án vẫn ghi nguồn AI kèm độ tin cậy thật để tra cứu sau.
                            </span>
                          </span>
                        </label>
                      )}
                    </div>
                  )}
                  {bulkSummary && (
                    <div style={{ marginTop: 10, background: "#F0FDF4", color: "#14532D", border: "1px solid #86C79B", borderRadius: 10, padding: "10px 14px", fontSize: 13.5 }}>
                      <b>Đã duyệt {bulkSummary.approved} câu vào kho.</b>
                      {bulkSummary.skipped.length > 0 && (
                        <>
                          <span> Bỏ qua {bulkSummary.skipped.length} câu:</span>
                          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                            {Object.entries(bulkSummary.skipped.reduce<Record<string, number>>((acc, s) => {
                              acc[s.reason] = (acc[s.reason] || 0) + 1; return acc;
                            }, {})).map(([reason, n]) => (
                              <li key={reason}>{n} câu — {reason}</li>
                            ))}
                          </ul>
                        </>
                      )}
                    </div>
                  )}
                </div>
                {queue && queue.total === 0 && <p>Hàng đợi trống — mọi câu của đề này đã được xử lý.</p>}
                {groups.map((g) => {
                  const activeItem = g.items.find((it) => it.id === activeQ)
                    || g.items.find((it) => it.status === "needs_answer")
                    || g.items[0];
                  const activeBlank = activeItem ? blankNoOf(activeItem) : null;
                  const blanks = new Set(g.items.map((it) => blankNoOf(it)).filter((n): n is number => n != null));
                  return (
                    <div key={g.key}>
                      {g.passage && (
                        <div style={{ ...box, marginBottom: 10 }}>
                          <div style={{ fontSize: 13, color: "#4A5578", fontWeight: 650, marginBottom: 8 }}>
                            📖 Đoạn văn dùng chung cho {g.items.length} chỗ trống — chỗ trống đang xem được tô đậm, bấm vào thẻ câu để chuyển.
                          </div>
                          <div style={{ background: "#F7FAFF", border: "1px solid #E3E8F4", borderRadius: 12, padding: 14, fontSize: 14.5, lineHeight: 1.7 }}
                            dangerouslySetInnerHTML={{ __html: highlightPassage(g.passage.passage_html || g.passage.passage_text || "", !!g.passage.passage_html, activeBlank, blanks) }} />
                        </div>
                      )}
                      {g.items.map((q) => reviewCard(q, !!g.passage, activeItem?.id === q.id))}
                    </div>
                  );
                })}
              </>
            );
          })()}
        </section>
      )}

      {tab === "builder" && (
        <section>
          <div style={{ ...box, marginBottom: 12 }}>
            <b>Mẫu đề của tôi</b>
            <span style={{ color: "#4A5578", fontSize: 13 }}> — tự dựng mẫu theo đúng kho câu của bạn. Số liệu "kho có" là câu đã duyệt + có đáp án.</span>
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
              <div key={i} style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 8, background: "#F4F6FB", borderRadius: 12, padding: 8 }}>
                <input value={s.name} onChange={(e) => setSection(i, { name: e.target.value })} style={{ padding: 8, flex: 1 }} placeholder="Tên phần" />
                <select value={s.question_type} onChange={(e) => setSection(i, { question_type: e.target.value })} style={{ padding: 8 }}>
                  {qtypes.map((qt) => (<option key={qt.id} value={qt.code}>{qt.label}</option>))}
                </select>
                <span style={{ fontSize: 12, color: "#4A5578" }}>
                  kho có: {avail[s.question_type] ? `${avail[s.question_type].standalone} độc lập · ${avail[s.question_type].with_passage} gắn đoạn` : "0 câu"}
                </span>
                <label style={{ fontSize: 13 }}>Số câu <input type="number" min={1} value={s.question_count} onChange={(e) => setSection(i, { question_count: Number(e.target.value) })} style={{ padding: 7, width: 60 }} /></label>
                <label style={{ fontSize: 13 }}><input type="checkbox" checked={s.with_passage} onChange={(e) => setSection(i, { with_passage: e.target.checked })} /> Gắn đoạn văn</label>
                <span style={{ fontSize: 12, color: "#4A5578" }}>% NB/TH/VD/VDC:</span>
                {(["nb", "th", "vd", "vdc"] as const).map((k) => (
                  <input key={k} value={s[k]} onChange={(e) => setSection(i, { [k]: e.target.value } as Partial<TplSectionForm>)}
                    style={{ padding: 7, width: 44 }} placeholder={k.toUpperCase()} />
                ))}
                <button style={btn} onClick={() => setTplSections((prev) => prev.filter((_, j) => j !== i))}>✕</button>
              </div>
            ))}
            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
              <button style={btn} onClick={() => setTplSections((prev) => [...prev, { name: `Phần ${prev.length + 1}`, question_type: "vocabulary_mc", question_count: 5, with_passage: false, nb: "", th: "", vd: "", vdc: "" }])}>+ Thêm phần</button>
              <button style={{ padding: "8px 14px", background: "#15803D", color: "#fff", border: 0, borderRadius: 12, fontWeight: 700 }} onClick={saveTemplate}>
                {editTplId ? "Lưu thay đổi" : "Lưu mẫu mới"}
              </button>
              {editTplId && <button style={btn} onClick={() => setEditTplId(null)}>Huỷ sửa</button>}
              <span style={{ fontSize: 13, color: "#4A5578", alignSelf: "center" }}>
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
            <button style={{ padding: "9px 16px", background: "#2547D0", color: "#fff", border: 0, borderRadius: 12, fontWeight: 700 }} onClick={doGenerate}>
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
              <div style={{ marginTop: 12, borderTop: "1px solid #E3E8F4", paddingTop: 10 }}>
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
    </div>
  );
}
