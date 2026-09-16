import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep DATABASE_URL and other secrets out of client bundles.
  serverExternalPackages: ["postgres"],
};

export default nextConfig;
