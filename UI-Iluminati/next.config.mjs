/** @type {import('next').NextConfig} */
const nextConfig = {
  // Separate build dirs let a second dev server run side by side (NEXT_DIST_DIR=.next-alt).
  distDir: process.env.NEXT_DIST_DIR || ".next",
  images: {
    unoptimized: true,
  },
}

export default nextConfig
