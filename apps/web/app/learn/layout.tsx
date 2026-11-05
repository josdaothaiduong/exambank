import "../learn-tokens.css";
import "./learn.css";
import Link from "next/link";

export default function LearnLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="learn-wrap">
      <header className="learn-row" style={{ justifyContent: "space-between", marginBottom: 16 }}>
        <Link href="/learn" className="text-h3" style={{ color: "inherit", textDecoration: "none" }}>
          ExamBank Learn
        </Link>
        <nav className="learn-row">
          <Link href="/learn">Đề của tôi</Link>
          <Link href="/learn/teacher">Khu giáo viên</Link>
          <Link href="/">ExamBank</Link>
        </nav>
      </header>
      {children}
    </div>
  );
}
