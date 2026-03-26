import { decodeJwt } from "jose";
import type { SessionData } from "./types";

const AGENTOS_URL =
  process.env.AGENTOS_INTERNAL_URL || "http://localhost:7777";

export interface AuthProvider {
  login(credentials: {
    email: string;
    password: string;
  }): Promise<SessionData>;
  signup(data: {
    email: string;
    password: string;
    name?: string;
  }): Promise<SessionData>;
  // Future SSO methods
  getOAuthUrl?(): Promise<string>;
  handleOAuthCallback?(code: string, state: string): Promise<SessionData>;
}

function jwtToSessionData(jwt: string, email: string): SessionData {
  const claims = decodeJwt(jwt);
  return {
    jwt,
    userId: (claims.sub as string) || "",
    email,
    expiresAt: (claims.exp as number) || 0,
  };
}

export const credentialsProvider: AuthProvider = {
  async login({ email, password }) {
    const res = await fetch(`${AGENTOS_URL}/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      if (res.status === 404) {
        throw new Error(
          "Auth service not available. Please ensure the backend has auth endpoints configured.",
        );
      }
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || "Invalid email or password");
    }
    const data = await res.json();
    return jwtToSessionData(data.access_token, email);
  },

  async signup({ email, password, name }) {
    const res = await fetch(`${AGENTOS_URL}/v1/auth/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, name }),
    });
    if (!res.ok) {
      if (res.status === 404) {
        throw new Error(
          "Auth service not available. Please ensure the backend has auth endpoints configured.",
        );
      }
      if (res.status === 409) {
        throw new Error("An account with this email already exists");
      }
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || "Signup failed. Please try again.");
    }
    const data = await res.json();
    return jwtToSessionData(data.access_token, email);
  },
};

// Swap this to entraProvider when migrating to Microsoft Entra
export const activeProvider = credentialsProvider;
