import { ToolsPage } from "../../components/tools-page";

type ToolsSearchParams = Promise<{ q?: string | string[] }>;

export default async function Page({
  searchParams,
}: {
  searchParams?: ToolsSearchParams;
}) {
  const params = await searchParams;
  const query = Array.isArray(params?.q) ? params.q[0] : params?.q;
  return <ToolsPage initialQuery={query || ""} />;
}
