import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  reactStrictMode: false,
  reactCompiler: true,
  transpilePackages: ["livekit-client", "@livekit/components-react"],
  turbopack: {
    // Ensuring the root is absolute as required by Turbopack
    root: path.resolve("."), 
  },
};

export default nextConfig;
