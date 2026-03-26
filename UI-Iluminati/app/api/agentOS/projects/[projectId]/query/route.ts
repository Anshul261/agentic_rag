import { proxySSE } from "@/lib/auth/proxy";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ projectId: string }> },
) {
  const { projectId } = await params;
  const formData = await req.formData();
  return proxySSE(`/projects/${projectId}/query`, formData);
}
