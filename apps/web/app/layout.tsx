export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body style={{ fontFamily: "system-ui, Arial, sans-serif", margin: 24 }}>{children}</body>
    </html>
  );
}
