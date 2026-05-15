/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // Only proxy /api internally when running in Docker dev mode
    // (NEXT_PUBLIC_API_URL is the internal backend hostname).
    // In production/nginx mode, API_URL is an external HTTPS domain
    // and nginx handles proxying — so we must NOT rewrite here.
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "";
    if (apiUrl.includes("backend:8000") || apiUrl.includes("localhost:8000")) {
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
