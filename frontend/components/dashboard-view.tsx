"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Activity, MessageSquare, ShoppingBag, TrendingUp } from "lucide-react"
import { Bar, BarChart, CartesianGrid, XAxis, YAxis, ResponsiveContainer } from "recharts"
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart"

const statsData = [
  { title: "运行中账号", value: "12", change: "+2", icon: Activity, color: "text-chart-1" },
  { title: "今日匹配", value: "248", change: "+18%", icon: MessageSquare, color: "text-chart-2" },
  { title: "已抓取商品", value: "1,547", change: "+127", icon: ShoppingBag, color: "text-chart-3" },
  { title: "转化率", value: "68.2%", change: "+5.1%", icon: TrendingUp, color: "text-chart-4" },
]

const chartData = [
  { day: "周一", matches: 186 },
  { day: "周二", matches: 305 },
  { day: "周三", matches: 237 },
  { day: "周四", matches: 273 },
  { day: "周五", matches: 209 },
  { day: "周六", matches: 214 },
  { day: "周日", matches: 248 },
]

export function DashboardView() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight">概览仪表板</h2>
        <p className="text-muted-foreground">实时监控系统运行状态和关键指标</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {statsData.map((stat, index) => (
          <Card key={index}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">{stat.title}</CardTitle>
              <stat.icon className={`size-4 ${stat.color}`} />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stat.value}</div>
              <p className="text-xs text-muted-foreground mt-1">
                <span className="text-emerald-600 font-medium">{stat.change}</span> 较昨日
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>本周匹配趋势</CardTitle>
          <CardDescription>过去 7 天的消息匹配数量统计</CardDescription>
        </CardHeader>
        <CardContent>
          <ChartContainer
            config={{
              matches: {
                label: "匹配数",
                color: "hsl(var(--chart-1))",
              },
            }}
            className="h-[300px]"
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="day" />
                <YAxis />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Bar dataKey="matches" fill="var(--color-matches)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </ChartContainer>
        </CardContent>
      </Card>
    </div>
  )
}
