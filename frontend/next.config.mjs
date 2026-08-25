import { dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  turbopack: {
    root: __dirname,
  },
  async rewrites() {
    // Only proxy /api internally when running in Docker dev mode
    // (NEXT_PUBLIC_API_URL is the internal backend hostname).
    // In production/nginx mode, API_URL is an external HTTPS domain
    // and nginx handles proxying — so we must NOT rewrite here.
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "";
    if (apiUrl.includes("backend:8000") || apiUrl.includes("localhost:8000") || apiUrl.includes("localhost:28000")) {
      return [
        {
          source: "/api/:path*",
          destination: `${apiUrl}/api/:path*`,
        },
      ];
    }
    return [];
  },
};

export default nextConfig;
