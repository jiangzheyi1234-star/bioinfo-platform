import type { ReactNode } from "react";

import { SshShellProvider } from "./ssh-shell";

export function AppShell({ children }: { children: ReactNode }) {
  return <SshShellProvider>{children}</SshShellProvider>;
}
