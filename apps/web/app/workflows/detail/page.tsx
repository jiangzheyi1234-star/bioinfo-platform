import { Suspense } from "react";

import { WorkflowDetailPage } from "../../components/workflow-detail-page";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <WorkflowDetailPage />
    </Suspense>
  );
}
