"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../lib/api";

interface LearnClass { id: string; name: string; grade: number; school_year: string; join_code: string; student_count: number }
interface StudentRow { student_user_id: string; display_name: string; birth_year: number; status: string; consent: { student_self: boolean; parent_guardian: boolean } }
interface CreatedStudent { display_name: string; login_email: string; student_code: string; initial_password_once: string }
interface EnrollReq { id: string; display_name: string; birth_year: number | null; status: string; message: string | null }
interface AssignmentRow { id: string; title: string; mode: string; status: string; question_count: number | null }
interface AtomRow { id: string; headword: string; atom_type: string; front_text: string; back_text: string; meaning_vi: string; priority: string; common_error_code: string | null; status: string; origin: string; ai_confidence: number | null; needs_teacher_confirmation: boolean; source_question_stem: string | null; sources: { source_role: string }[]; variants: { id: string; variant_tier: string; status: string }[] }
interface VariantRow { id: string; variant_tier: string; stem_text: string; status: string; correct_option_id: string | null; options: { option_id: string; label: string; content_text: string }[] }
interface ContentRow { id: string; question_id: string; question_stem: string | null; status: string; ai_confidence: number | null; needs_teacher_confirmation: boolean; content: { error_code: string | null; why_wrong: string; cue: string; rule: string } }
interface SourceExam { id: string; title: string }
interface Workspace { id: string; name: string }

const iso = (v: string) => (v ? new Date(v).toISOString() : "");
const plusDays = (d: number) => {
  const t = new Date(Date.now() + d * 864e5);
  return t.toISOString().slice(0, 16);
};

export default function TeacherLearnPage() {
  const [classes, setClasses] = useState<LearnClass[]>([]);
  const [cls, setCls] = useState<LearnClass | null>(null);
  const [students, setStudents] = useState<StudentRow[]>([]);
  const [created, setCreated] = useState<CreatedStudent[]>([]);
  const [requests, setRequests] = useState<EnrollReq[]>([]);
  const [assignments, setAssignments] = useState<AssignmentRow[]>([]);
  const [sources, setSources] = useState<SourceExam[]>([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [form, setForm] = useState({ name: "", grade: 11, school_year: "2026-2027" });
  const [one, setOne] = useState({ display_name: "", birth_year: 2009 });
  const [bulk, setBulk] = useState("");
  const [asg, setAsg] = useState({ source_exam_id: "", exam_version_id: "", mode: "paper_quick_entry", opens_at: plusDays(0), due_at: plusDays(1), answer_release_at: plusDays(1) });
  // --- Kho hạt (EL-202/203/204)
  const [atoms, setAtoms] = useState<AtomRow[]>([]);
  const [atomStatus, setAtomStatus] = useState("pending_review");
  const [pendingAtoms, setPendingAtoms] = useState(0);
  const [contents, setContents] = useState<ContentRow[]>([]);
  const [pendingContents, setPendingContents] = useState(0);
  const [genExamId, setGenExamId] = useState("");
  const [editAtom, setEditAtom] = useState<AtomRow | null>(null);
  const [variantsByAtom, setVariantsByAtom] = useState<Record<string, VariantRow[]>>({});

  const loadClasses = useCallback(async () => {
    try {
      const rows = await api<LearnClass[]>("/api/v1/learn/classes");
      setClasses(rows);
    } catch (e: any) { setError(e.message); }
  }, []);

  const loadClassDetail = useCallback(async (c: LearnClass) => {
    setCls(c);
    try {
      const [st, rq, as] = await Promise.all([
        api<StudentRow[]>(`/api/v1/learn/classes/${c.id}/students`),
        api<EnrollReq[]>(`/api/v1/learn/classes/${c.id}/enrollment-requests`),
        api<AssignmentRow[]>(`/api/v1/learn/classes/${c.id}/assignments`),
      ]);
      setStudents(st); setRequests(rq); setAssignments(as);
    } catch (e: any) { setError(e.message); }
  }, []);

  useEffect(() => {
    loadClasses();
    (async () => {
      try {
        const wss = await api<Workspace[]>("/api/v1/workspaces");
        if (wss[0]) {
          const src = await api<SourceExam[]>(`/api/v1/source-exams?workspace_id=${wss[0].id}`);
          setSources(src);
        }
      } catch {}
    })();
  }, [loadClasses]);

  async function createClass(e: React.FormEvent) {
    e.preventDefault(); setError(""); setMsg("");
    try {
      const c = await api<LearnClass>("/api/v1/learn/classes", { method: "POST", body: JSON.stringify(form) });
      await loadClasses(); setMsg(`Đã tạo lớp ${c.name} — mã lớp (join_code): ${c.join_code}`);
    } catch (e: any) { setError(e.message); }
  }

  async function addStudents(list: { display_name: string; birth_year: number }[]) {
    if (!cls || !list.length) return;
    setError(""); setMsg("");
    try {
      const r = await api<{ created: CreatedStudent[] }>(`/api/v1/learn/classes/${cls.id}/students`, {
        method: "POST", body: JSON.stringify({ students: list }),
      });
      setCreated(r.created);
      await loadClassDetail(cls);
    } catch (e: any) { setError(e.message); }
  }

  async function decide(id: string, action: "approve" | "reject") {
    try {
      await api(`/api/v1/learn/enrollment-requests/${id}/decision`, { method: "POST", body: JSON.stringify({ action }) });
      if (cls) await loadClassDetail(cls);
    } catch (e: any) { setError(e.message); }
  }

  async function createAssignment(e: React.FormEvent) {
    e.preventDefault(); if (!cls) return;
    setError(""); setMsg("");
    try {
      const body: any = {
        class_id: cls.id, mode: asg.mode,
        opens_at: iso(asg.opens_at), due_at: iso(asg.due_at), answer_release_at: iso(asg.answer_release_at),
      };
      if (asg.exam_version_id.trim()) body.exam_version_id = asg.exam_version_id.trim();
      else body.source_exam_id = asg.source_exam_id;
      const a = await api<AssignmentRow>("/api/v1/learn/assignments", { method: "POST", body: JSON.stringify(body) });
      const p = await api<AssignmentRow>(`/api/v1/learn/assignments/${a.id}/publish`, { method: "POST", body: "{}" });
      setMsg(`Đã giao & publish "${p.title}" (${p.question_count} câu) cho lớp ${cls.name}`);
      await loadClassDetail(cls);
    } catch (e: any) { setError(e.message); }
  }

  // --- Kho hạt: tải/duyệt/sinh (EL-202/203/204)
  const loadAtoms = useCallback(async (st: string) => {
    try {
      const r = await api<{ items: AtomRow[]; pending_total: number }>(`/api/v1/learn/atoms?status=${st}&limit=200`);
      setAtoms(r.items); setPendingAtoms(r.pending_total);
    } catch (e: any) { setError(e.message); }
  }, []);

  const loadContents = useCallback(async () => {
    try {
      const r = await api<{ items: ContentRow[]; pending_total: number }>("/api/v1/learn/post-test-contents?limit=200");
      setContents(r.items); setPendingContents(r.pending_total);
    } catch (e: any) { setError(e.message); }
  }, []);

  useEffect(() => { loadAtoms(atomStatus); loadContents(); }, [atomStatus, loadAtoms, loadContents]);

  async function approveWithConfirm(url: string) {
    try {
      await api(url, { method: "POST", body: JSON.stringify({ confirm_answer: false }) });
    } catch (e: any) {
      if (String(e.message).includes("TEACHER_CONFIRMATION_REQUIRED")) {
        if (!window.confirm("Nội dung này suy từ câu chưa có đáp án chắc chắn. Thầy cô xác nhận đáp án là đúng?")) throw e;
        await api(url, { method: "POST", body: JSON.stringify({ confirm_answer: true }) });
      } else if (String(e.message).includes("ATOM_LOW_CONFIDENCE")) {
        throw new Error("Độ tin cậy AI < 0,70 — hãy bấm 'Xem' mở nội dung trước khi duyệt.");
      } else throw e;
    }
  }

  async function atomAction(a: AtomRow, action: "approve" | "reject") {
    setError(""); setMsg("");
    try {
      if (action === "approve") await approveWithConfirm(`/api/v1/learn/atoms/${a.id}/approve`);
      else await api(`/api/v1/learn/atoms/${a.id}/reject`, { method: "POST", body: "{}" });
      setMsg(`${action === "approve" ? "Đã duyệt" : "Đã loại"} hạt "${a.headword}"`);
      await loadAtoms(atomStatus);
    } catch (e: any) { setError(e.message); }
  }

  async function viewAtom(a: AtomRow) {
    try {
      const full = await api<AtomRow>(`/api/v1/learn/atoms/${a.id}`);
      setEditAtom(full);
    } catch (e: any) { setError(e.message); }
  }

  async function saveAtomEdit() {
    if (!editAtom) return;
    try {
      await api(`/api/v1/learn/atoms/${editAtom.id}`, {
        method: "PATCH",
        body: JSON.stringify({ headword: editAtom.headword, front_text: editAtom.front_text, back_text: editAtom.back_text, meaning_vi: editAtom.meaning_vi, priority: editAtom.priority }),
      });
      setEditAtom(null); setMsg("Đã lưu hạt (nếu hạt đã duyệt, nó quay về chờ duyệt lại).");
      await loadAtoms(atomStatus);
    } catch (e: any) { setError(e.message); }
  }

  async function bulkApproveP1() {
    const ids = atoms.filter((a) => a.status === "pending_review" && a.priority === "P1").map((a) => a.id);
    if (!ids.length) { setMsg("Không có hạt P1 đang chờ duyệt trong danh sách."); return; }
    try {
      const r = await api<{ approved: string[]; skipped: { atom_id: string; code: string }[] }>("/api/v1/learn/atoms/bulk-approve", {
        method: "POST", body: JSON.stringify({ atom_ids: ids }),
      });
      setMsg(`Duyệt nhanh: ${r.approved.length} hạt đạt${r.skipped.length ? `, bỏ qua ${r.skipped.length} hạt (${r.skipped.map((s) => s.code).join(", ")})` : ""}`);
      await loadAtoms(atomStatus);
    } catch (e: any) { setError(e.message); }
  }

  async function generateAtomsForExam() {
    if (!genExamId) return;
    setError(""); setMsg("");
    try {
      const r = await api<{ eligible_questions: number; atoms_created: number; atoms_total: number; cap: number }>(
        `/api/v1/learn/source-exams/${genExamId}/atom-generation`, { method: "POST", body: JSON.stringify({ force: false }) });
      setMsg(`Đã bẻ hạt: ${r.eligible_questions} câu đạt chuẩn, tạo mới ${r.atoms_created} hạt (tổng ${r.atoms_total}/${r.cap}). Hạt đang chờ duyệt ở dưới.`);
      await loadAtoms(atomStatus); await loadContents();
    } catch (e: any) { setError(e.message); }
  }

  async function toggleVariants(a: AtomRow) {
    if (variantsByAtom[a.id]) { setVariantsByAtom((m) => { const n = { ...m }; delete n[a.id]; return n; }); return; }
    try {
      const r = await api<{ items: VariantRow[] }>(`/api/v1/learn/variants?atom_id=${a.id}`);
      setVariantsByAtom((m) => ({ ...m, [a.id]: r.items }));
    } catch (e: any) { setError(e.message); }
  }

  async function genVariantP2(a: AtomRow) {
    try {
      const r = await api<{ variant_id: string | null; status: string }>(`/api/v1/learn/atoms/${a.id}/variant-generation-jobs`, {
        method: "POST", body: JSON.stringify({ force: false }),
      });
      setMsg(`Biến thể P2 cho "${a.headword}": ${r.status}${r.variant_id ? "" : " (chưa sinh được)"}`);
      const vr = await api<{ items: VariantRow[] }>(`/api/v1/learn/variants?atom_id=${a.id}`);
      setVariantsByAtom((m) => ({ ...m, [a.id]: vr.items }));
    } catch (e: any) { setError(e.message); }
  }

  async function variantAction(atomId: string, v: VariantRow, action: "approve" | "reject") {
    try {
      if (action === "approve") await approveWithConfirm(`/api/v1/learn/variants/${v.id}/approve`);
      else await api(`/api/v1/learn/variants/${v.id}/reject`, { method: "POST", body: "{}" });
      const vr = await api<{ items: VariantRow[] }>(`/api/v1/learn/variants?atom_id=${atomId}`);
      setVariantsByAtom((m) => ({ ...m, [atomId]: vr.items }));
    } catch (e: any) { setError(e.message); }
  }

  async function contentAction(ct: ContentRow, action: "approve" | "reject") {
    try {
      if (action === "approve") await approveWithConfirm(`/api/v1/learn/post-test-contents/${ct.id}/approve`);
      else await api(`/api/v1/learn/post-test-contents/${ct.id}/reject`, { method: "POST", body: "{}" });
      await loadContents();
    } catch (e: any) { setError(e.message); }
  }

  return (
    <main>
      <h1 className="text-h1">Lớp của tôi</h1>
      {error && <p className="learn-error">{error}</p>}
      {msg && <p className="learn-ok">{msg}</p>}

      <section className="learn-card">
        <h2 className="text-h2">Tạo lớp</h2>
        <form onSubmit={createClass} className="learn-grid" style={{ gridTemplateColumns: "2fr 1fr 1fr auto" }}>
          <input className="learn-input" placeholder="Tên lớp (vd 11A2)" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          <input className="learn-input" type="number" min={10} max={12} value={form.grade} onChange={(e) => setForm({ ...form, grade: Number(e.target.value) })} />
          <input className="learn-input" value={form.school_year} onChange={(e) => setForm({ ...form, school_year: e.target.value })} />
          <button className="learn-btn learn-btn-primary">Tạo lớp</button>
        </form>
        <div className="learn-row" style={{ marginTop: 12 }}>
          {classes.map((c) => (
            <button key={c.id} className="learn-btn" onClick={() => loadClassDetail(c)}>
              {c.name} · khối {c.grade} · {c.student_count} HS · mã lớp: <b>{c.join_code}</b>
            </button>
          ))}
          {!classes.length && <span className="learn-muted">Chưa có lớp nào.</span>}
        </div>
      </section>

      {cls && (
        <>
          <section className="learn-card">
            <h2 className="text-h2">Học sinh lớp {cls.name} <span className="learn-muted">(mã lớp: {cls.join_code})</span></h2>
            <table className="learn-table">
              <thead><tr><th>Họ tên</th><th>Năm sinh</th><th>Trạng thái</th><th>Đồng ý HS/PH</th></tr></thead>
              <tbody>
                {students.map((s) => (
                  <tr key={s.student_user_id}><td>{s.display_name}</td><td className="numeric">{s.birth_year}</td><td>{s.status}</td>
                    <td>{s.consent.student_self ? "HS ✓" : "HS —"} / {s.consent.parent_guardian ? "PH ✓" : "PH —"}</td></tr>
                ))}
                {!students.length && <tr><td colSpan={4} className="learn-muted">Chưa có học sinh.</td></tr>}
              </tbody>
            </table>
            <div className="learn-grid" style={{ gridTemplateColumns: "1fr 1fr", marginTop: 16 }}>
              <form onSubmit={(e) => { e.preventDefault(); addStudents([one]); }} className="learn-grid">
                <b>Thêm từng em</b>
                <input className="learn-input" placeholder="Họ tên" value={one.display_name} onChange={(e) => setOne({ ...one, display_name: e.target.value })} required />
                <input className="learn-input" type="number" value={one.birth_year} onChange={(e) => setOne({ ...one, birth_year: Number(e.target.value) })} />
                <button className="learn-btn">Thêm học sinh</button>
              </form>
              <form onSubmit={(e) => {
                e.preventDefault();
                const list = bulk.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
                  const [name, year] = l.split(",").map((x) => x.trim());
                  return { display_name: name, birth_year: Number(year) || 2009 };
                });
                addStudents(list);
              }} className="learn-grid">
                <b>Dán danh sách (mỗi dòng: Họ tên, năm sinh)</b>
                <textarea className="learn-input" rows={4} value={bulk} onChange={(e) => setBulk(e.target.value)} placeholder={"Nguyễn Văn A, 2009\nTrần Thị B, 2010"} />
                <button className="learn-btn">Thêm cả danh sách</button>
              </form>
            </div>
            {created.length > 0 && (
              <div className="learn-notyet" style={{ marginTop: 12 }}>
                <b>Tài khoản vừa cấp — mật khẩu chỉ hiện 1 lần, hãy ghi lại:</b>
                {created.map((s) => (<div key={s.login_email}>{s.display_name}: {s.login_email} / {s.initial_password_once}</div>))}
              </div>
            )}
          </section>

          <section className="learn-card">
            <h2 className="text-h2">Hàng chờ đăng ký (tự đăng ký bằng mã lớp)</h2>
            {requests.map((r) => (
              <div key={r.id} className="learn-row" style={{ justifyContent: "space-between" }}>
                <span>{r.display_name} · {r.birth_year ?? "?"} {r.message ? `· ${r.message}` : ""}</span>
                <span className="learn-row">
                  <button className="learn-btn learn-btn-primary" onClick={() => decide(r.id, "approve")}>Duyệt</button>
                  <button className="learn-btn" onClick={() => decide(r.id, "reject")}>Từ chối</button>
                </span>
              </div>
            ))}
            {!requests.length && <p className="learn-muted">Không có yêu cầu đang chờ.</p>}
          </section>

          <section className="learn-card">
            <h2 className="text-h2">Giao đề cho lớp {cls.name}</h2>
            <form onSubmit={createAssignment} className="learn-grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
              <label>Đề gốc (ExamBank)
                <select className="learn-input" value={asg.source_exam_id} onChange={(e) => setAsg({ ...asg, source_exam_id: e.target.value })}>
                  <option value="">— chọn đề gốc —</option>
                  {sources.map((s) => (<option key={s.id} value={s.id}>{s.title}</option>))}
                </select>
              </label>
              <label>hoặc Exam version ID (đã sinh ở ExamBank)
                <input className="learn-input" value={asg.exam_version_id} onChange={(e) => setAsg({ ...asg, exam_version_id: e.target.value })} placeholder="Để trống nếu dùng đề gốc" />
              </label>
              <label>Hình thức
                <select className="learn-input" value={asg.mode} onChange={(e) => setAsg({ ...asg, mode: e.target.value })}>
                  <option value="paper_quick_entry">Làm giấy — nhập đáp án</option>
                  <option value="online">Làm online</option>
                </select>
              </label>
              <label>Mở lúc<input className="learn-input" type="datetime-local" value={asg.opens_at} onChange={(e) => setAsg({ ...asg, opens_at: e.target.value })} /></label>
              <label>Hạn nộp<input className="learn-input" type="datetime-local" value={asg.due_at} onChange={(e) => setAsg({ ...asg, due_at: e.target.value })} /></label>
              <label>Mở đáp án lúc<input className="learn-input" type="datetime-local" value={asg.answer_release_at} onChange={(e) => setAsg({ ...asg, answer_release_at: e.target.value })} /></label>
              <button className="learn-btn learn-btn-primary">Giao & publish ngay</button>
            </form>
            <ul>
              {assignments.map((a) => (<li key={a.id}>{a.title} — {a.mode} — {a.status}{a.question_count ? ` — ${a.question_count} câu` : ""}</li>))}
            </ul>
          </section>
        </>
      )}

      <section className="learn-card">
        <h2 className="text-h2">Kho hạt & hậu-đề <span className="learn-muted">({pendingAtoms} hạt + {pendingContents} nội dung hậu-đề đang chờ duyệt)</span></h2>
        <div className="learn-row">
          <select className="learn-input" style={{ maxWidth: 320 }} value={genExamId} onChange={(e) => setGenExamId(e.target.value)}>
            <option value="">— chọn đề gốc để bẻ hạt —</option>
            {sources.map((s) => (<option key={s.id} value={s.id}>{s.title}</option>))}
          </select>
          <button className="learn-btn learn-btn-primary" onClick={generateAtomsForExam} disabled={!genExamId}>Bẻ hạt từ đề này (AI)</button>
          <span className="learn-muted">Sinh 1 lần/câu, tối đa 3 hạt/câu, 120 hạt/đề. Hạt chưa duyệt không tới được học sinh.</span>
        </div>

        <div className="learn-row" style={{ marginTop: 16 }}>
          <b>Lọc hạt:</b>
          {["pending_review", "approved", "rejected"].map((st) => (
            <button key={st} className="learn-btn" aria-pressed={atomStatus === st} onClick={() => setAtomStatus(st)}>
              {st === "pending_review" ? "Chờ duyệt" : st === "approved" ? "Đã duyệt" : "Đã loại"}
            </button>
          ))}
          <button className="learn-btn" onClick={bulkApproveP1}>Duyệt nhanh các hạt P1 đang hiện</button>
        </div>

        {atoms.map((a) => (
          <div key={a.id} style={{ borderBottom: "1px solid var(--border)", padding: "10px 0" }}>
            <div className="learn-row" style={{ justifyContent: "space-between" }}>
              <span><b>{a.headword}</b> · {a.atom_type} · {a.priority}{a.common_error_code ? ` · lỗi ${a.common_error_code}` : ""}
                {" · "}<span className="learn-muted">nguồn: {a.sources.map((s) => s.source_role).join(", ") || "câu gốc"}{a.ai_confidence !== null ? ` · AI tin cậy ${a.ai_confidence}` : ""}{a.needs_teacher_confirmation ? " · CẦN XÁC NHẬN ĐÁP ÁN" : ""}</span></span>
              <span className="learn-row">
                <button className="learn-btn" onClick={() => viewAtom(a)}>Xem / Sửa</button>
                {a.status !== "approved" && <button className="learn-btn learn-btn-primary" onClick={() => atomAction(a, "approve")}>Duyệt</button>}
                {a.status !== "rejected" && <button className="learn-btn" onClick={() => atomAction(a, "reject")}>Loại</button>}
                <button className="learn-btn" onClick={() => toggleVariants(a)}>Biến thể ({a.variants.length})</button>
                {a.status === "approved" && <button className="learn-btn" onClick={() => genVariantP2(a)}>Sinh biến thể P2</button>}
              </span>
            </div>
            <div className="learn-muted" style={{ marginTop: 4 }}>Câu gốc: {a.source_question_stem}</div>
            <div>Mặt hỏi: {a.front_text}</div>
            <div>Mặt đáp án: {a.back_text}</div>
            <div className="learn-muted">Nghĩa: {a.meaning_vi}</div>
            {editAtom?.id === a.id && (
              <div className="learn-grid" style={{ marginTop: 8 }}>
                <input className="learn-input" value={editAtom.headword} onChange={(e) => setEditAtom({ ...editAtom, headword: e.target.value })} placeholder="headword" />
                <textarea className="learn-input" rows={2} value={editAtom.front_text} onChange={(e) => setEditAtom({ ...editAtom, front_text: e.target.value })} placeholder="Mặt hỏi" />
                <textarea className="learn-input" rows={2} value={editAtom.back_text} onChange={(e) => setEditAtom({ ...editAtom, back_text: e.target.value })} placeholder="Mặt đáp án" />
                <input className="learn-input" value={editAtom.meaning_vi} onChange={(e) => setEditAtom({ ...editAtom, meaning_vi: e.target.value })} placeholder="Nghĩa Việt" />
                <select className="learn-input" value={editAtom.priority} onChange={(e) => setEditAtom({ ...editAtom, priority: e.target.value })}>
                  <option>P1</option><option>P2</option><option>P3</option>
                </select>
                <span className="learn-row">
                  <button className="learn-btn learn-btn-primary" onClick={saveAtomEdit}>Lưu hạt</button>
                  <button className="learn-btn" onClick={() => setEditAtom(null)}>Đóng</button>
                </span>
              </div>
            )}
            {variantsByAtom[a.id]?.map((v) => (
              <div key={v.id} className="learn-row" style={{ justifyContent: "space-between", marginLeft: 16, marginTop: 6 }}>
                <span>{v.variant_tier === "T2" ? "P2 (ngữ cảnh mới)" : "P1 (cơ học)"} · {v.status} — {v.stem_text} <span className="learn-muted">({v.options.map((o) => `${o.label}.${o.content_text}`).join(" · ")})</span></span>
                <span className="learn-row">
                  {v.status !== "approved" && <button className="learn-btn learn-btn-primary" onClick={() => variantAction(a.id, v, "approve")}>Duyệt biến thể</button>}
                  {v.status !== "rejected" && <button className="learn-btn" onClick={() => variantAction(a.id, v, "reject")}>Loại</button>}
                </span>
              </div>
            ))}
          </div>
        ))}
        {!atoms.length && <p className="learn-muted">Không có hạt ở trạng thái này.</p>}

        <h3 className="text-h3" style={{ marginTop: 20 }}>Nội dung hậu-đề (4 bước) chờ duyệt</h3>
        {contents.filter((ct) => ct.status === "pending_review").map((ct) => (
          <div key={ct.id} style={{ borderBottom: "1px solid var(--border)", padding: "8px 0" }}>
            <div className="learn-muted">Câu: {ct.question_stem}{ct.needs_teacher_confirmation ? " · CẦN XÁC NHẬN ĐÁP ÁN" : ""}</div>
            <div>Vì sao sai: {ct.content.why_wrong}</div>
            <div>Cue: {ct.content.cue} · Quy tắc: {ct.content.rule}</div>
            <span className="learn-row" style={{ marginTop: 6 }}>
              <button className="learn-btn learn-btn-primary" onClick={() => contentAction(ct, "approve")}>Duyệt hậu-đề</button>
              <button className="learn-btn" onClick={() => contentAction(ct, "reject")}>Loại</button>
            </span>
          </div>
        ))}
        {!contents.some((ct) => ct.status === "pending_review") && <p className="learn-muted">Không có nội dung hậu-đề đang chờ duyệt.</p>}
      </section>
    </main>
  );
}
