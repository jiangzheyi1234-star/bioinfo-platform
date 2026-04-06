import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "H2OMeta Desktop Workbench",
  description: "FastAPI + Next.js + Tauri desktop workbench",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
