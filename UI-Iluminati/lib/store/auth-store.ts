import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { SafeUser, AuthResult } from "@/lib/auth/types";

interface AuthState {
  user: SafeUser | null;
  status: "loading" | "authenticated" | "unauthenticated";
  setUser: (user: SafeUser) => void;
  clearUser: () => void;
  setStatus: (status: AuthState["status"]) => void;
  login: (credentials: {
    email: string;
    password: string;
  }) => Promise<AuthResult>;
  signup: (data: {
    email: string;
    password: string;
    name?: string;
  }) => Promise<AuthResult>;
  logout: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      status: "loading",

      setUser: (user) => set({ user, status: "authenticated" }),
      clearUser: () => set({ user: null, status: "unauthenticated" }),
      setStatus: (status) => set({ status }),

      login: async (credentials) => {
        const res = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(credentials),
        });
        const data: AuthResult = await res.json();
        if (data.ok) {
          set({ user: data.user, status: "authenticated" });
        }
        return data;
      },

      signup: async (data) => {
        const res = await fetch("/api/auth/signup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        });
        const result: AuthResult = await res.json();
        if (result.ok) {
          set({ user: result.user, status: "authenticated" });
        }
        return result;
      },

      logout: async () => {
        await fetch("/api/auth/logout", { method: "POST" });
        set({ user: null, status: "unauthenticated" });
      },
    }),
    {
      name: "auth-storage",
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({
        user: state.user,
      }),
    },
  ),
);
