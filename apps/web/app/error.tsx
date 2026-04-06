"use client";

import { useEffect } from "react";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("App route error boundary:", error);
  }, [error]);

  return (
    <main style={{ padding: 24 }}>
      <section
        style={{
          border: "1px solid #ef4444",
          borderRadius: 10,
          background: "rgba(127, 29, 29, 0.2)",
          padding: 16,
          color: "#fecaca",
          maxWidth: 980,
          margin: "0 auto",
        }}
      >
        <h2 style={{ marginTop: 0 }}>前端运行时错误</h2>
        <p style={{ color: "#fecaca" }}>{error?.message || "Unknown client-side error"}</p>
        {error?.digest ? <p style={{ color: "#fca5a5" }}>digest: {error.digest}</p> : null}
        <button
          onClick={reset}
          style={{
            marginTop: 10,
            border: "1px solid #f87171",
            background: "transparent",
            color: "#fecaca",
            borderRadius: 8,
            padding: "8px 12px",
            cursor: "pointer",
          }}
        >
          重试页面
        </button>
      </section>
    </main>
  );
}
