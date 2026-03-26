"use client";

import { useEffect } from "react";
import { useAuthStore } from "@/lib/store/auth-store";

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const setUser = useAuthStore((s) => s.setUser);
    const clearUser = useAuthStore((s) => s.clearUser);

    useEffect(() => {
        fetch("/api/auth/session")
            .then((r) => r.json())
            .then((data) => {
                if (data.isAuthenticated) {
                    setUser(data.user);
                } else {
                    clearUser();
                }
            })
            .catch(() => {
                clearUser();
            });
    }, [setUser, clearUser]);

    return <>{children}</>;
}
