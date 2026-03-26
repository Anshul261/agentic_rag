import { NextResponse } from "next/server";
import { z } from "zod";
import { getSession, toSafeUser } from "@/lib/auth/session";
import { activeProvider } from "@/lib/auth/provider";

const LoginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

export async function POST(req: Request) {
  const body = LoginSchema.safeParse(await req.json());
  if (!body.success) {
    return NextResponse.json(
      { ok: false, error: "Invalid email or password format" },
      { status: 400 },
    );
  }

  try {
    const sessionData = await activeProvider.login(body.data);
    const session = await getSession();
    session.jwt = sessionData.jwt;
    session.userId = sessionData.userId;
    session.email = sessionData.email;
    session.expiresAt = sessionData.expiresAt;
    await session.save();

    return NextResponse.json({ ok: true, user: toSafeUser(sessionData) });
  } catch (e) {
    const message = e instanceof Error ? e.message : "Login failed";
    return NextResponse.json({ ok: false, error: message }, { status: 401 });
  }
}
