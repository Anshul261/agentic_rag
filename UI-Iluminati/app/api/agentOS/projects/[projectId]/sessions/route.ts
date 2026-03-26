import { proxyGet } from "@/lib/auth/proxy";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ projectId: string }> },
) {
  const { projectId } = await params;
  return proxyGet(`/projects/${projectId}/sessions`);
}
