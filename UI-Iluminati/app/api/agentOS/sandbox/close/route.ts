import { proxyPost } from "@/lib/auth/proxy";

export async function POST() {
  return proxyPost("/sandbox/close", "");
}
