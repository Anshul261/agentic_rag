import { config } from "dotenv";

config({ path: "../.env" });

import { config as loadEnv } from "dotenv";

loadEnv({ path: "../.env" });

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
