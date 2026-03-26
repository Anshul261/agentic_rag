import { proxyGet, proxyPost } from "@/lib/auth/proxy";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const qs = searchParams.toString();
  return proxyGet(`/sessions${qs ? `?${qs}` : ""}`);
}

export async function POST(req: Request) {
  const body = await req.text();
  return proxyPost("/sessions?type=team", body, {
    "Content-Type": "application/json",
  });
}
