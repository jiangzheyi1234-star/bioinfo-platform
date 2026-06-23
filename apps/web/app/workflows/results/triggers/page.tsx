import { Suspense } from "react";

import { WorkflowTriggerObservabilityPage } from "../../../components/workflow-trigger-observability-page";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <WorkflowTriggerObservabilityPage />
    </Suspense>
  );
}
