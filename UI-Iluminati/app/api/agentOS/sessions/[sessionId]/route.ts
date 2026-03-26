import { proxyGet, proxyDelete } from "@/lib/auth/proxy";

export async function GET(
  req: Request,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params;
  const { searchParams } = new URL(req.url);
  const qs = searchParams.toString();
  return proxyGet(`/sessions/${sessionId}${qs ? `?${qs}` : ""}`);
}

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await params;
  return proxyDelete(`/sessions/${sessionId}`);
}
