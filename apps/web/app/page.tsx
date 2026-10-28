export default function Home() {
  return (
    <main>
      <h1>ExamBank AI</h1>
      <p>EB-101: Khung web đã khởi tạo. Giao diện đầy đủ (port từ prototype Bước 2) thuộc EB-106.</p>
      <p>API: {process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/health</p>
    </main>
  );
}
