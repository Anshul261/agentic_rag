import { proxyGet } from "@/lib/auth/proxy";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params;
  const { searchParams } = new URL(req.url);
  const qs = searchParams.toString();
  return proxyGet(`/sessions/${sessionId}/runs${qs ? `?${qs}` : ""}`);
}
