import { Suspense } from "react";

import { ToolsPage } from "../../components/tools-page";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <ToolsPage />
    </Suspense>
  );
}
