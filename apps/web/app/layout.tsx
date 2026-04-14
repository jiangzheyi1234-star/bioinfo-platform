import type { ReactNode } from "react";

export const metadata = {
  title: "H2OMeta Web Reset",
  description: "Blank frontend baseline for incremental redesign.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
