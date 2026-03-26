import { NextResponse } from "next/server";
import { z } from "zod";
import { getSession, toSafeUser } from "@/lib/auth/session";
import { activeProvider } from "@/lib/auth/provider";

const SignupSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8, "Password must be at least 8 characters"),
  name: z.string().optional(),
});

export async function POST(req: Request) {
  const body = SignupSchema.safeParse(await req.json());
  if (!body.success) {
    return NextResponse.json(
      { ok: false, error: body.error.issues[0]?.message || "Invalid input" },
      { status: 400 },
    );
  }

  try {
    const sessionData = await activeProvider.signup(body.data);
    const session = await getSession();
    session.jwt = sessionData.jwt;
    session.userId = sessionData.userId;
    session.email = sessionData.email;
    session.expiresAt = sessionData.expiresAt;
    await session.save();

    return NextResponse.json({ ok: true, user: toSafeUser(sessionData) });
  } catch (e) {
    const message = e instanceof Error ? e.message : "Signup failed";
    return NextResponse.json({ ok: false, error: message }, { status: 400 });
  }
}
