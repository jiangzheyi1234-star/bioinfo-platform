import { Suspense } from "react";

import { WorkflowConsolePage } from "../components/workflow_console_page";

export default function WorkspacePage() {
  return (
    <Suspense fallback={null}>
      <WorkflowConsolePage />
    </Suspense>
  );
}
