import { Suspense } from "react";

import { WorkflowResultDetailPage } from "../../../components/workflow-result-detail-page";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <WorkflowResultDetailPage />
    </Suspense>
  );
}
