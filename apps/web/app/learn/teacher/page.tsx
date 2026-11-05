"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../../lib/api";

interface LearnClass { id: string; name: string; grade: number; school_year: string; join_code: string; student_count: number }
interface StudentRow { student_user_id: string; display_name: string; birth_year: number; status: string; consent: { student_self: boolean; parent_guardian: boolean } }
interface CreatedStudent { display_name: string; login_email: string; student_code: string; initial_password_once: string }
interface EnrollReq { id: string; display_name: string; birth_year: number | null; status: string; message: string | null }
interface AssignmentRow { id: string; title: string; mode: string; status: string; question_count: number | null }
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
    </main>
  );
}
