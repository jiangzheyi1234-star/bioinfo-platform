import { Suspense } from "react";

import { WorkspaceRouteRedirect } from "../components/workspace_route_redirect";

export default function WorkflowsRedirectPage() {
  return (
    <Suspense fallback={null}>
      <WorkspaceRouteRedirect target="/workspace" />
    </Suspense>
  );
}
