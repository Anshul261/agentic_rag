import { config } from "dotenv";

// Load shared .env from project root (in containers, env vars are set directly)
config({ path: "../.env" });

/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
}

export default nextConfig
