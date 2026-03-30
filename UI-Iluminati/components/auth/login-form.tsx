"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/lib/store/auth-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sparkles } from "lucide-react";

export function LoginForm() {
    const router = useRouter();
    const login = useAuthStore((s) => s.login);
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError("");
        setLoading(true);

        try {
            const result = await login({ email, password });
            if (result.ok) {
                router.push("/");
            } else {
                setError(result.error);
            }
        } catch {
            setError("An unexpected error occurred");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="w-full max-w-sm space-y-8">
            <div className="text-center space-y-3">
                <div className="mx-auto w-12 h-12 rounded-sm border border-primary/30 flex items-center justify-center">
                    <Sparkles className="w-5 h-5 text-primary" />
                </div>
                <h1 className="font-sans text-2xl font-semibold tracking-tight text-foreground">
                    Welcome back
                </h1>
                <p className="text-xs text-muted-foreground font-mono uppercase tracking-widest">
                    Sign in to your account
                </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-2">
                    <Label htmlFor="email" className="font-mono text-xs uppercase tracking-wider">
                        Email
                    </Label>
                    <Input
                        id="email"
                        type="email"
                        placeholder="you@example.com"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required
                        className="font-mono text-sm"
                    />
                </div>

                <div className="space-y-2">
                    <Label htmlFor="password" className="font-mono text-xs uppercase tracking-wider">
                        Password
                    </Label>
                    <Input
                        id="password"
                        type="password"
                        placeholder="••••••••"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        required
                        className="font-mono text-sm"
                    />
                </div>

                {error && (
                    <p className="text-sm text-destructive font-mono">{error}</p>
                )}

                <Button
                    type="submit"
                    className="w-full font-mono text-xs uppercase tracking-wider"
                    disabled={loading}
                >
                    {loading ? "Signing in..." : "Sign in"}
                </Button>
            </form>

            <p className="text-center text-xs text-muted-foreground font-mono">
                Don&apos;t have an account?{" "}
                <Link
                    href="/signup"
                    className="text-primary underline-offset-4 hover:underline"
                >
                    Sign up
                </Link>
            </p>
        </div>
    );
}
