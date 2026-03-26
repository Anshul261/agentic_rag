import { NextResponse } from "next/server";
import { requireSession, SessionExpiredError } from "./session";

const AGENTOS_URL =
  process.env.AGENTOS_INTERNAL_URL || "http://localhost:7777";

function authHeaders(jwt: string): Record<string, string> {
  return { Authorization: `Bearer ${jwt}` };
}

export async function proxyGet(upstreamPath: string) {
  try {
    const session = await requireSession();
    const res = await fetch(`${AGENTOS_URL}${upstreamPath}`, {
      headers: authHeaders(session.jwt),
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

export async function proxyPost(
  upstreamPath: string,
  body: BodyInit,
  headers?: Record<string, string>,
) {
  try {
    const session = await requireSession();
    const res = await fetch(`${AGENTOS_URL}${upstreamPath}`, {
      method: "POST",
      headers: { ...authHeaders(session.jwt), ...headers },
      body,
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

export async function proxyDelete(upstreamPath: string) {
  try {
    const session = await requireSession();
    const res = await fetch(`${AGENTOS_URL}${upstreamPath}`, {
      method: "DELETE",
      headers: authHeaders(session.jwt),
    });
    if (res.status === 204) {
      return new NextResponse(null, { status: 204 });
    }
    const data = await res.json().catch(() => ({}));
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

export async function proxySSE(upstreamPath: string, body: BodyInit) {
  try {
    const session = await requireSession();
    const upstream = await fetch(`${AGENTOS_URL}${upstreamPath}`, {
      method: "POST",
      headers: {
        ...authHeaders(session.jwt),
        "Accept-Encoding": "identity",
      },
      body,
    });

    if (!upstream.ok || !upstream.body) {
      const data = await upstream.json().catch(() => ({}));
      return NextResponse.json(
        { error: data.detail || "Upstream error" },
        { status: upstream.status },
      );
    }

    return new Response(upstream.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
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

export { AGENTOS_URL, authHeaders };
