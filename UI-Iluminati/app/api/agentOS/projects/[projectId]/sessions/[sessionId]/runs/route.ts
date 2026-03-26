import { proxyGet } from "@/lib/auth/proxy";

export async function GET(
  _req: Request,
  {
    params,
  }: { params: Promise<{ projectId: string; sessionId: string }> },
) {
  const { projectId, sessionId } = await params;
  return proxyGet(
    `/projects/${projectId}/sessions/${sessionId}/runs`,
  );
}
