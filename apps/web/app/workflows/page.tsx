import { Suspense } from "react";

import { AgentWorkbenchPage } from "../components/agent-workbench-page";

export default function Page() {
  return (
    <Suspense fallback={<div className="h-full w-full bg-slate-50" aria-label="正在加载 Agent 工作台" />}>
      <AgentWorkbenchPage />
    </Suspense>
  );
}
