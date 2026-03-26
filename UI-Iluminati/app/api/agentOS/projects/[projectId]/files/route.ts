import { AGENTOS_URL, authHeaders } from "@/lib/auth/proxy";
import { requireSession, SessionExpiredError } from "@/lib/auth/session";
import { NextResponse } from "next/server";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ projectId: string }> },
) {
  const { projectId } = await params;
  try {
    const session = await requireSession();
    const formData = await req.formData();
    const res = await fetch(`${AGENTOS_URL}/projects/${projectId}/files`, {
      method: "POST",
      headers: authHeaders(session.jwt),
      body: formData,
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    if (e instanceof SessionExpiredError) {
      return NextResponse.json({ error: "Session expired" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 },
    );
  }
}
