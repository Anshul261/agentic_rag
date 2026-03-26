import { proxyGet, proxyDelete } from "@/lib/auth/proxy";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ projectId: string }> },
) {
  const { projectId } = await params;
  return proxyGet(`/projects/${projectId}`);
}

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ projectId: string }> },
) {
  const { projectId } = await params;
  return proxyDelete(`/projects/${projectId}`);
}
