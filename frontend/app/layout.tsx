import type { Metadata } from "next"
import type React from "react"
import { Bricolage_Grotesque, IBM_Plex_Mono } from "next/font/google"
import { Analytics } from "@vercel/analytics/next"
import { Toaster } from "sonner"
import "./globals.css"

const bricolage = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--app-font-sans",
})

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  variable: "--app-font-mono",
  weight: ["400", "500", "600"],
})

export const metadata: Metadata = {
  title: "LinkRadar Desktop",
  description: "LinkRadar Windows desktop app for Discord marketing automation.",
  generator: "v0.app",
  icons: {
    icon: [
      {
        url: "/icon-light-32x32.png",
        media: "(prefers-color-scheme: light)",
      },
      {
        url: "/icon-dark-32x32.png",
        media: "(prefers-color-scheme: dark)",
      },
      {
        url: "/icon.svg",
        type: "image/svg+xml",
      },
    ],
    apple: "/apple-icon.png",
  },
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="zh-CN">
      <body className={`${bricolage.variable} ${plexMono.variable} font-sans antialiased`}>
        {children}
        <Toaster richColors position="top-right" />
        <Analytics />
      </body>
    </html>
  )
}
