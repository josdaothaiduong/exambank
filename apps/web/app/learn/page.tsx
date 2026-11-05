"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "../../lib/api";

interface MyAssignment {
  assignment_id: string; title: string; class_name: string; mode: string;
  opens_at: string; due_at: string; answer_release_at: string;
  question_count: number | null; attempt: { id: string; status: string } | null;
}
interface ConsentStatus { profile_status: string; granted: string[]; missing: string[] }
interface Child { student_user_id: string; display_name: string; profile_status: string; class: { id: string; name: string } | null }

const fmt = (s: string) => new Date(s).toLocaleString("vi-VN");

export default function LearnHomePage() {
  const [items, setItems] = useState<MyAssignment[]>([]);
  const [consent, setConsent] = useState<ConsentStatus | null>(null);
  const [children, setChildren] = useState<Child[]>([]);
  const [role, setRole] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const me = await api<{ role: string }>("/api/v1/auth/me");
        setRole(me.role);
        if (me.role === "student") {
          const [a, cs] = await Promise.all([
            api<MyAssignment[]>("/api/v1/learn/my/assignments"),
            api<ConsentStatus>("/api/v1/learn/my/consent-status"),
          ]);
          setItems(a); setConsent(cs);
        } else if (me.role === "parent") {
          setChildren(await api<Child[]>("/api/v1/learn/my/children"));
        }
      } catch (e: any) { setError(e.message); }
    })();
  }, []);

  async function selfConsent() {
    try {
      const cs = await api<ConsentStatus & { profile_status: string }>("/api/v1/learn/my/consent", {
        method: "POST", body: JSON.stringify({ policy_version: "v1-2026" }),
      });
      setConsent(cs);
      setMsg("Đã ghi nhận đồng ý của em.");
    } catch (e: any) { setError(e.message); }
  }

  return (
    <main>
      <h1 className="text-h1">{role === "parent" ? "Theo dõi việc học" : "Đề của tôi"}</h1>
      {error && <p className="learn-error">{error}</p>}
      {msg && <p className="learn-ok">{msg}</p>}

      {role === "student" && consent && consent.profile_status !== "active" && (
        <section className="learn-card">
          <h2 className="text-h2">Đồng ý sử dụng</h2>
          <p className="text-body">
            Để bắt đầu học, cần đủ 2 đồng ý: của em {consent.granted.includes("student_self") ? "✓" : "—"} và của phụ huynh{" "}
            {consent.granted.includes("parent_guardian") ? "✓" : "—"}. Phụ huynh có thể ký phiếu giấy nộp thầy cô hoặc nhận mã liên kết từ thầy cô.
          </p>
          {!consent.granted.includes("student_self") && (
            <button className="learn-btn learn-btn-primary" onClick={selfConsent}>Em đồng ý (chính sách bảo vệ dữ liệu trẻ em v1-2026)</button>
          )}
        </section>
      )}

      {role === "student" && items.map((a) => (
        <section key={a.assignment_id} className="learn-card learn-row" style={{ justifyContent: "space-between" }}>
          <div>
            <div className="text-h3">{a.title}</div>
            <div className="learn-muted">
              {a.class_name} · {a.mode === "online" ? "Làm online" : "Làm giấy — nhập đáp án"} · {a.question_count ?? "?"} câu
              <br />Mở: {fmt(a.opens_at)} — Hạn: {fmt(a.due_at)} — Đáp án mở: {fmt(a.answer_release_at)}
              {a.attempt ? ` · Bài làm: ${a.attempt.status}` : ""}
            </div>
          </div>
          <Link href={`/learn/do/${a.assignment_id}`}>
            <button className="learn-btn learn-btn-primary">{a.attempt?.status === "in_progress" ? "Làm tiếp" : a.mode === "online" ? "Vào làm bài" : "Nhập đáp án"}</button>
          </Link>
        </section>
      ))}
      {role === "student" && !items.length && <p className="learn-muted">Chưa có đề nào được giao.</p>}

      {role === "parent" && children.map((c) => (
        <section key={c.student_user_id} className="learn-card">
          <div className="text-h3">{c.display_name}</div>
          <div className="learn-muted">Lớp: {c.class?.name ?? "—"} · Trạng thái hồ sơ: {c.profile_status}</div>
        </section>
      ))}
      {role === "teacher" && (
        <p className="text-body">Thầy cô đang đăng nhập bằng tài khoản giáo viên. Vào <Link href="/learn/teacher">Khu giáo viên</Link> để quản lý lớp và giao đề.</p>
      )}
    </main>
  );
}
