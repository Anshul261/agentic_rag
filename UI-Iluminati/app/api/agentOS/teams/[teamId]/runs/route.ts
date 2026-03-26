import { proxySSE } from "@/lib/auth/proxy";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ teamId: string }> },
) {
  const { teamId } = await params;
  const formData = await req.formData();
  return proxySSE(`/teams/${teamId}/runs`, formData);
}
