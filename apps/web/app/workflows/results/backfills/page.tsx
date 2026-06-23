import { Suspense } from "react";

import { WorkflowBackfillLaunchesPage } from "../../../components/workflow-backfill-launches-page";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <WorkflowBackfillLaunchesPage />
    </Suspense>
  );
}
