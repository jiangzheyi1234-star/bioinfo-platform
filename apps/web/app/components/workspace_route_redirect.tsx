"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

type WorkspaceRouteRedirectProps = {
  target: string;
};

export function WorkspaceRouteRedirect({ target }: WorkspaceRouteRedirectProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const query = searchParams.toString();
    router.replace(query ? `${target}?${query}` : target);
  }, [router, searchParams, target]);

  return null;
}
