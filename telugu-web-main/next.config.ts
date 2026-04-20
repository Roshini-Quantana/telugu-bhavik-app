import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  reactCompiler: true,
  turbopack: {
    // Ensuring the root is absolute as required by Turbopack
    root: path.resolve("."), 
  },
};

export default nextConfig;
