import { proxyDelete } from "@/lib/auth/proxy";

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ projectId: string; fileId: string }> },
) {
  const { projectId, fileId } = await params;
  return proxyDelete(`/projects/${projectId}/files/${fileId}`);
}
