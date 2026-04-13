import { Suspense } from "react";

import { ProjectConnectionPage } from "../components/project_connection_page";

export default function ConnectPage() {
  return (
    <Suspense fallback={null}>
      <ProjectConnectionPage />
    </Suspense>
  );
}
