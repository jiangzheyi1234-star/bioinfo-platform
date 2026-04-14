import "./globals.css";
import type { ReactNode } from "react";

import { AppShell } from "./components/app_shell";

export const metadata = {
  title: "H2OMeta",
  description: "Blank frontend baseline for incremental redesign.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
