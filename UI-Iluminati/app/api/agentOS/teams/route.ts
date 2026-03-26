import { proxyGet } from "@/lib/auth/proxy";

export async function GET() {
  return proxyGet("/teams");
}
