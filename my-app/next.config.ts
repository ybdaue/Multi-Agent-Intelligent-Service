import type { NextConfig } from "next";

const configInit = () => {
  const nextConfig: NextConfig = {
    reactCompiler: true,
    reactStrictMode: true,
    devIndicators: false,
    async rewrites() {
      return [
        {
          source: "/api/finance/:path*",
          destination: `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/finance/:path*`,
        },
        {
          source: "/api/agent/:path*",
          destination: `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/agent/:path*`,
        },
      ];
    },
    headers: () => {
      return [
        {
          source: "/(.*)", // 匹配所有路径
          headers: [
            {
              key: "Access-Control-Allow-Origin",
              // TODO: 生产环境应限制为具体域名，而非通配符 "*"
              value: "*",
            },
            {
              key: "Access-Control-Allow-Methods", // 允许的HTTP方法
              value: "GET, POST, PUT, DELETE, PATCH, OPTIONS", // 允许的HTTP方法
            },
            {
              key: "Access-Control-Allow-Headers", // 允许的HTTP请求头
              value: "X-Requested-With, Content-Type, Authorization", // 允许的HTTP请求头
            },
          ],
        },
        {
          source: "/api/(.*)", // 匹配所有以 /api/ 开头的路径
          headers: [
            {
              key: "X-API-Version", // 自定义HTTP响应头
              value: "1.0", // 自定义HTTP响应头的值
            },
          ],
        },
      ];
    },
  };
  return nextConfig;
};

export default configInit;
