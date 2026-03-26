import { NextResponse } from "next/server";
import { AGENTOS_URL, authHeaders } from "@/lib/auth/proxy";
import { requireSession, SessionExpiredError } from "@/lib/auth/session";

export async function GET() {
  try {
    const session = await requireSession();
    // Scope projects to the authenticated user
    const res = await fetch(
      `${AGENTOS_URL}/projects?user_id=${encodeURIComponent(session.userId)}`,
      { headers: authHeaders(session.jwt) },
    );
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

export async function POST(req: Request) {
  try {
    const session = await requireSession();
    const body = await req.json();
    // Inject userId from session, not from client
    const res = await fetch(`${AGENTOS_URL}/projects`, {
      method: "POST",
      headers: {
        ...authHeaders(session.jwt),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ...body, user_id: session.userId }),
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
