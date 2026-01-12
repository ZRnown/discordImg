/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false, // 关闭React严格模式，避免开发环境下双重调用
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
}

export default nextConfig
