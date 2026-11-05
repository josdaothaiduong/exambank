"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "../../../../lib/api";

interface OptBrief { option_id: string; label: string; content_text: string }
interface PostItem {
  question_id: string; position: number; question_type: string;
  stem_text: string; kind: "wrong" | "correct_unsure";
  your_option: OptBrief | null; correct_option: OptBrief | null;
  content_status: "ready" | "preparing";
  progress: { current_step: number; status: string };
}
interface PostList { attempt_id: string; title: string; items: PostItem[] }

export default function PostTestListPage() {
  const params = useParams<{ attemptId: string }>();
  const [data, setData] = useState<PostList | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        setData(await api<PostList>(`/api/v1/learn/attempts/${params.attemptId}/post-test`));
      } catch (e: any) { setError(e.message); }
    })();
  }, [params.attemptId]);

  return (
    <main>
      <h1 className="text-h1">Xem lại câu chưa đúng</h1>
      <p className="text-body">Đây là lần làm đầu. Câu chưa đúng là để ôn lại cho nhớ — không phải để buồn.</p>
      {error && <p className="learn-error">{error}</p>}
      {data && <p className="learn-muted">{data.title} · {data.items.length} câu cần xem lại</p>}
      {data && data.items.length === 0 && (
        <section className="learn-card">
          <p className="text-body">Bạn đúng tất cả các câu ở lần làm này. Các câu đúng vẫn sẽ quay lại thưa dần để chắc chắn bạn nhớ lâu.</p>
        </section>
      )}
      {data?.items.map((it) => (
        <section key={it.question_id} className="learn-card">
          <div className="learn-row" style={{ justifyContent: "space-between" }}>
            <b>Câu {it.position} · {it.question_type}</b>
            <span className="learn-muted">
              {it.progress.status === "completed" ? "Đã sửa xong ✓" : it.progress.current_step > 0 ? `Đang sửa — xong ${it.progress.current_step}/4 bước` : "Chưa xem lại"}
            </span>
          </div>
          <p className="text-body" style={{ marginTop: 8 }}>{it.stem_text}</p>
          <p className="text-body">
            Bạn chọn: <b>{it.your_option ? `${it.your_option.label}. ${it.your_option.content_text}` : "(bỏ trống)"}</b>
            {" · "}Đáp án đúng: <b>{it.correct_option ? `${it.correct_option.label}. ${it.correct_option.content_text}` : "?"}</b>
          </p>
          {it.content_status === "ready" ? (
            <Link href={`/learn/review/${params.attemptId}/${it.question_id}`}>
              <button className="learn-btn learn-btn-primary">{it.progress.status === "completed" ? "Xem lại 4 bước" : "Xem lại câu này"}</button>
            </Link>
          ) : (
            <p className="learn-notyet">Đang chuẩn bị phần giải thích… (thầy cô đang duyệt nội dung)</p>
          )}
        </section>
      ))}
      <Link href="/learn">← Về Đề của tôi</Link>
    </main>
  );
}
