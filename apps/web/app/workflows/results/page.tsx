import { Suspense } from "react";

import { WorkflowResultsPage } from "../../components/workflow-results-page";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <WorkflowResultsPage />
    </Suspense>
  );
}
