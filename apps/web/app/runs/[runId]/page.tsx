import { redirect } from "next/navigation";

export function generateStaticParams() {
  return [{ runId: "run_2026_0419_001" }];
}

export default function Page() {
  redirect("/servers");
}
