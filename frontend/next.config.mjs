/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false, // 关闭React严格模式，避免开发环境下双重调用
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:5001/api/:path*',
      },
    ]
  },
}

export default nextConfig
