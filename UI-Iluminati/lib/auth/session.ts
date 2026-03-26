import { getIronSession, type IronSession } from "iron-session";
import { cookies } from "next/headers";
import type { SessionData } from "./types";

const COOKIE_NAME = "__iluminati_session";

function getSessionOptions() {
  const password = process.env.SECRET_KEY;
  if (!password || password.length < 32) {
    throw new Error("SECRET_KEY env var must be at least 32 characters");
  }
  return {
    password,
    cookieName: COOKIE_NAME,
    cookieOptions: {
      secure: process.env.NODE_ENV === "production",
      httpOnly: true,
      sameSite: "lax" as const,
      maxAge: 60 * 60 * 8, // 8 hours
    },
  };
}

export async function getSession(): Promise<IronSession<SessionData>> {
  const cookieStore = await cookies();
  return getIronSession<SessionData>(cookieStore, getSessionOptions());
}

export async function requireSession(): Promise<SessionData> {
  const session = await getSession();
  if (!session.jwt || Date.now() / 1000 > session.expiresAt - 300) {
    throw new SessionExpiredError();
  }
  return {
    jwt: session.jwt,
    userId: session.userId,
    email: session.email,
    expiresAt: session.expiresAt,
  };
}

export function toSafeUser(session: SessionData) {
  return { userId: session.userId, email: session.email };
}

export class SessionExpiredError extends Error {
  constructor() {
    super("Session expired");
    this.name = "SessionExpiredError";
  }
}
