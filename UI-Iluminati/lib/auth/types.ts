// Session data stored in the encrypted httpOnly cookie (server-side only)
export interface SessionData {
  jwt: string;
  userId: string;
  email: string;
  expiresAt: number;
}

// Safe user info that the browser is allowed to see (no JWT)
export interface SafeUser {
  userId: string;
  email: string;
}

// Response shape from BFF auth routes
export type AuthResult =
  | { ok: true; user: SafeUser }
  | { ok: false; error: string };
