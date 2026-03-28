import { proxySSE } from "@/lib/auth/proxy";

export async function POST(req: Request) {
  const formData = await req.formData();
  return proxySSE("/sandbox/query", formData);
}
