import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  logging: {
    fetches: {
      fullUrl: true,
    },
  },
  serverExternalPackages: [],
};

export default nextConfig;
