import { redirect } from "next/navigation";

export function generateStaticParams() {
  return [{ projectId: "proj_default" }];
}

export default function Page() {
  redirect("/servers");
}
