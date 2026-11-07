"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, setToken } from "../../lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const path = mode === "login" ? "/api/v1/auth/login" : "/api/v1/auth/register";
      const body = mode === "login" ? { email, password } : { email, password, full_name: fullName };
      const data = await api<{ access_token: string }>(path, { method: "POST", body: JSON.stringify(body) });
      setToken(data.access_token);
      // Learn: HS/PH vào thẳng khu học tập sau đăng nhập; GV về ExamBank
      if (mode === "login") {
        try {
          const me = await api<{ role: string }>("/api/v1/auth/me");
          router.push(me.role === "student" || me.role === "parent" ? "/learn" : "/");
        } catch {
          router.push("/");
        }
      } else {
        router.push("/");
      }
    } catch (err: any) {
      setError(err.message || "Đăng nhập thất bại");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 24, background: "linear-gradient(135deg, #101B3C 0%, #1B37A8 58%, #2547D0 100%)" }}>
      <div style={{ width: "min(420px, 100%)", background: "#fff", borderRadius: 16, padding: 28, boxShadow: "0 24px 48px -16px rgb(0 0 0 / .45)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <span style={{ width: 40, height: 40, borderRadius: 12, background: "linear-gradient(135deg, #2547D0, #7C3AED)", display: "grid", placeItems: "center", fontSize: 20 }}>📚</span>
          <h1 style={{ margin: 0, fontSize: 26 }}>ExamBank AI</h1>
        </div>
        <p style={{ color: "#4A5578", marginTop: 4 }}>{mode === "login" ? "Đăng nhập để vào ngân hàng đề của bạn." : "Đăng ký — hệ thống tự tạo workspace cá nhân cho bạn."}</p>
        <form onSubmit={submit} style={{ display: "grid", gap: 10 }}>
          {mode === "register" && (
            <input placeholder="Họ tên" value={fullName} onChange={(e) => setFullName(e.target.value)} required style={{ padding: 12 }} />
          )}
          <input placeholder="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required style={{ padding: 12 }} />
          <input placeholder="Mật khẩu (ít nhất 8 ký tự)" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required style={{ padding: 12 }} />
          {error && <p style={{ color: "#B91C1C", background: "#FEF2F2", border: "1px solid #FECACA", borderRadius: 12, padding: "9px 12px", margin: 0 }}>{error}</p>}
          <button disabled={busy} style={{ padding: 12, background: "#2547D0", color: "#fff", border: 0, borderRadius: 12, fontWeight: 700, minHeight: 48 }}>
            {busy ? "Đang xử lý..." : mode === "login" ? "Đăng nhập" : "Đăng ký"}
          </button>
        </form>
        <button onClick={() => setMode(mode === "login" ? "register" : "login")} style={{ marginTop: 14, background: "none", border: 0, color: "#2547D0", cursor: "pointer", fontWeight: 600, padding: 6 }}>
          {mode === "login" ? "Chưa có tài khoản? Đăng ký" : "Đã có tài khoản? Đăng nhập"}
        </button>
      </div>
    </main>
  );
}
