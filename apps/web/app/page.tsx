"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearToken, getToken, QuestionPage, SourceExam, Tag, Workspace } from "../lib/api";

export default function Home() {
  const router = useRouter();
  const [tab, setTab] = useState<"exams" | "bank" | "import" | "builder">("exams");
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
          {bank && bank.total === 0 && <p>Không có câu nào khớp bộ lọc. Câu hỏi sẽ xuất hiện sau khi nạp và duyệt đề (Tuần 2).</p>}
        </section>
      )}

      {tab === "import" && (
        <section style={box}>
          <h3>Nhập đề bằng copy-paste</h3>
          <p>Luồng này đã được kiểm chứng ở prototype Bước 2 (mở file <i>prototype/index.html</i> trong repo để dùng thử).</p>
          <p>Bản nối API thật (parser phía server, upload Word) thuộc <b>EB-201 → EB-206, Tuần 2</b> — chưa làm ở Tuần 1, không hiển thị dữ liệu giả ở đây.</p>
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
