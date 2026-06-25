import { Suspense } from "react";

import { WorkflowArtifactLifecyclePage } from "../../../components/workflow-artifact-lifecycle-page";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <WorkflowArtifactLifecyclePage />
    </Suspense>
  );
}
