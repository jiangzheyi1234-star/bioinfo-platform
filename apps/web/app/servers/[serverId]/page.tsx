import { ServerDetailPage } from "../../components/server-detail-page";

export function generateStaticParams() {
  return [{ serverId: "srv_demo" }];
}

export default async function Page({ params }: { params: Promise<{ serverId: string }> }) {
  const { serverId } = await params;
  return <ServerDetailPage serverId={serverId} />;
}
