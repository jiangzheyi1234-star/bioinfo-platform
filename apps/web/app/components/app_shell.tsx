import type { ReactNode } from "react";

import { SshShellProvider } from "./ssh-shell";
import { ToolPrepareTaskProvider } from "./tool-prepare-task-context";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <ToolPrepareTaskProvider>
      <SshShellProvider>{children}</SshShellProvider>
    </ToolPrepareTaskProvider>
  );
}
