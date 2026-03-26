import { NextResponse } from "next/server";
import { getSession, toSafeUser } from "@/lib/auth/session";

export async function GET() {
  const session = await getSession();

  if (!session.jwt || Date.now() / 1000 > session.expiresAt - 300) {
    return NextResponse.json({ isAuthenticated: false });
  }

  return NextResponse.json({
    isAuthenticated: true,
    user: toSafeUser(session),
  });
}
