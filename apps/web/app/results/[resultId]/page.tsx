import { redirect } from "next/navigation";

export function generateStaticParams() {
  return [{ resultId: "res_run_2026_0419_001" }];
}

export default function Page() {
  redirect("/servers");
}
