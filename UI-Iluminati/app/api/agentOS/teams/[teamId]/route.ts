import { proxyGet } from "@/lib/auth/proxy";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ teamId: string }> },
) {
  const { teamId } = await params;
  return proxyGet(`/teams/${teamId}`);
}
