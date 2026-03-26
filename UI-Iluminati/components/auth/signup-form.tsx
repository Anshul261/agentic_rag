"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/lib/store/auth-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Sparkles } from "lucide-react";

export function SignupForm() {
    const router = useRouter();
    const signup = useAuthStore((s) => s.signup);
    const [name, setName] = useState("");
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError("");

        if (password !== confirmPassword) {
            setError("Passwords do not match");
            return;
        }

        setLoading(true);

        try {
            const result = await signup({ email, password, name: name || undefined });
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
            <div className="text-center space-y-2">
                <div className="mx-auto w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
                    <Sparkles className="w-6 h-6 text-primary" />
                </div>
                <h1 className="font-serif text-2xl font-bold tracking-tight">
                    Create an account
                </h1>
                <p className="text-sm text-muted-foreground font-mono">
                    Get started with your AI assistant
                </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-2">
                    <Label htmlFor="name" className="font-mono text-xs uppercase tracking-wider">
                        Name (optional)
                    </Label>
                    <Input
                        id="name"
                        type="text"
                        placeholder="Your name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        className="font-mono"
                    />
                </div>

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
                        className="font-mono"
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
                        minLength={8}
                        className="font-mono"
                    />
                </div>

                <div className="space-y-2">
                    <Label htmlFor="confirmPassword" className="font-mono text-xs uppercase tracking-wider">
                        Confirm Password
                    </Label>
                    <Input
                        id="confirmPassword"
                        type="password"
                        placeholder="••••••••"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        required
                        minLength={8}
                        className="font-mono"
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
                    {loading ? "Creating account..." : "Create account"}
                </Button>
            </form>

            <p className="text-center text-sm text-muted-foreground font-mono">
                Already have an account?{" "}
                <Link
                    href="/login"
                    className="text-primary underline-offset-4 hover:underline"
                >
                    Sign in
                </Link>
            </p>
        </div>
    );
}
