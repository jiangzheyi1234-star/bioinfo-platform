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
    <main className="route-error-shell">
      <section className="route-error-card">
        <h2>前端运行时错误</h2>
        <p>{error?.message || "Unknown client-side error"}</p>
        {error?.digest ? <p>digest: {error.digest}</p> : null}
        <button onClick={reset}>重试页面</button>
      </section>
    </main>
  );
}
