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
      router.push("/");
    } catch (err: any) {
      setError(err.message || "Đăng nhập thất bại");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ maxWidth: 420, margin: "48px auto" }}>
      <h1>ExamBank AI</h1>
      <p>{mode === "login" ? "Đăng nhập để vào ngân hàng đề của bạn." : "Đăng ký — hệ thống tự tạo workspace cá nhân cho bạn."}</p>
      <form onSubmit={submit} style={{ display: "grid", gap: 10 }}>
        {mode === "register" && (
          <input placeholder="Họ tên" value={fullName} onChange={(e) => setFullName(e.target.value)} required style={{ padding: 10 }} />
        )}
        <input placeholder="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required style={{ padding: 10 }} />
        <input placeholder="Mật khẩu (ít nhất 8 ký tự)" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required style={{ padding: 10 }} />
        {error && <p style={{ color: "#b42318" }}>{error}</p>}
        <button disabled={busy} style={{ padding: 11, background: "#173a7a", color: "#fff", border: 0, borderRadius: 8, fontWeight: 700 }}>
          {busy ? "Đang xử lý..." : mode === "login" ? "Đăng nhập" : "Đăng ký"}
        </button>
      </form>
      <button onClick={() => setMode(mode === "login" ? "register" : "login")} style={{ marginTop: 12, background: "none", border: 0, color: "#173a7a", cursor: "pointer" }}>
        {mode === "login" ? "Chưa có tài khoản? Đăng ký" : "Đã có tài khoản? Đăng nhập"}
      </button>
    </main>
  );
}
