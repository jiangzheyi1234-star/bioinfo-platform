import "./globals.css";
import "./workspace.css";
import type { ReactNode } from "react";
import { WorkspaceRootShell } from "./components/workspace_root_shell";

export const metadata = {
  title: "H2OMeta Desktop Workbench",
  description: "FastAPI + Next.js + Tauri desktop workbench",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <WorkspaceRootShell>{children}</WorkspaceRootShell>
      </body>
    </html>
  );
}
