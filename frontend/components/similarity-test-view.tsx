"use client"

import type React from "react"
import { useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Upload, TestTube, AlertCircle, CheckCircle } from "lucide-react"
import { toast } from "sonner"
import { Alert, AlertDescription } from "@/components/ui/alert"

export function SimilarityTestView() {
  const [image1, setImage1] = useState<string | null>(null)
  const [image2, setImage2] = useState<string | null>(null)
  const [isTesting, setIsTesting] = useState(false)
  const [result, setResult] = useState<any>(null)

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>, imageNumber: 1 | 2) => {
    const file = e.target.files?.[0]
    if (!file) return

    if (!file.type.startsWith("image/")) {
      toast.error("请上传图片文件")
      return
    }

    const reader = new FileReader()
    reader.onload = (event) => {
      if (imageNumber === 1) {
        setImage1(event.target?.result as string)
      } else {
        setImage2(event.target?.result as string)
      }
      toast.success(`图片${imageNumber}已上传`)
    }
    reader.readAsDataURL(file)
  }

  const handleTest = async () => {
    if (!image1 || !image2) {
      toast.error("请上传两张图片")
      return
    }

    setIsTesting(true)
    setResult(null)

    try {
      // 将base64图片转换为blob
      const response1 = await fetch(image1)
      const blob1 = await response1.blob()

      const response2 = await fetch(image2)
      const blob2 = await response2.blob()

      // 创建FormData
      const formData = new FormData()
      formData.append('image1', blob1, 'image1.jpg')
      formData.append('image2', blob2, 'image2.jpg')

      // 发送到API进行相似度测试
      const testRes = await fetch('/api/test-similarity', {
        method: 'POST',
        body: formData
      })

      if (testRes.ok) {
        const data = await testRes.json()
        setResult(data)
        toast.success(`相似度测试完成: ${(data.similarity * 100).toFixed(2)}%`)
      } else {
        const errorText = await testRes.text()
        console.error('Test failed:', errorText)
        toast.error("测试失败: " + errorText)
      }
    } catch (error) {
      console.error('Test error:', error)
      toast.error("测试过程中发生错误")
    } finally {
      setIsTesting(false)
    }
  }

  const clearImages = () => {
    setImage1(null)
    setImage2(null)
    setResult(null)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <h2 className="text-3xl font-bold tracking-tight">相似度测试</h2>
          <p className="text-muted-foreground">测试PP-ShiTuV2模型对两张图片的相似度计算</p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>图片1</CardTitle>
            <CardDescription>选择第一张图片</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {!image1 ? (
              <label
                htmlFor="image1-upload"
                className="flex flex-col items-center justify-center h-48 border-2 border-dashed border-muted-foreground/25 rounded-lg cursor-pointer hover:border-muted-foreground/50 transition-colors"
              >
                <Upload className="size-12 text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">点击上传第一张图片</p>
                <input id="image1-upload" type="file" accept="image/*" className="hidden" onChange={(e) => handleFileUpload(e, 1)} />
              </label>
            ) : (
              <div className="relative">
                <img
                  src={image1}
                  alt="Image 1"
                  className="w-full h-48 object-contain rounded-lg border"
                />
                <Button
                  variant="destructive"
                  size="icon-sm"
                  className="absolute top-2 right-2"
                  onClick={() => setImage1(null)}
                >
                  ×
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>图片2</CardTitle>
            <CardDescription>选择第二张图片</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {!image2 ? (
              <label
                htmlFor="image2-upload"
                className="flex flex-col items-center justify-center h-48 border-2 border-dashed border-muted-foreground/25 rounded-lg cursor-pointer hover:border-muted-foreground/50 transition-colors"
              >
                <Upload className="size-12 text-muted-foreground mb-2" />
                <p className="text-sm text-muted-foreground">点击上传第二张图片</p>
                <input id="image2-upload" type="file" accept="image/*" className="hidden" onChange={(e) => handleFileUpload(e, 2)} />
              </label>
            ) : (
              <div className="relative">
                <img
                  src={image2}
                  alt="Image 2"
                  className="w-full h-48 object-contain rounded-lg border"
                />
                <Button
                  variant="destructive"
                  size="icon-sm"
                  className="absolute top-2 right-2"
                  onClick={() => setImage2(null)}
                >
                  ×
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TestTube className="size-5" />
            测试控制
          </CardTitle>
          <CardDescription>执行相似度测试</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-3">
            <Button
              onClick={handleTest}
              disabled={!image1 || !image2 || isTesting}
              className="flex-1"
            >
              <TestTube className="mr-2 size-4" />
              {isTesting ? "测试中..." : "开始相似度测试"}
            </Button>
            <Button
              variant="outline"
              onClick={clearImages}
              disabled={isTesting}
            >
              清空图片
            </Button>
          </div>

          {isTesting && (
            <div className="space-y-2">
              <Progress value={50} className="h-2" />
              <p className="text-[10px] text-blue-500 animate-pulse font-medium">正在提取特征向量并计算相似度...</p>
            </div>
          )}
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              {result.similarity > 0.9 ? (
                <CheckCircle className="size-5 text-green-500" />
              ) : (
                <AlertCircle className="size-5 text-orange-500" />
              )}
              测试结果
            </CardTitle>
            <CardDescription>PP-ShiTuV2模型相似度分析</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">相似度分数</span>
                  <Badge
                    className={
                      result.similarity > 0.9
                        ? "bg-green-600 hover:bg-green-700"
                        : result.similarity > 0.7
                        ? "bg-blue-600 hover:bg-blue-700"
                        : "bg-orange-600 hover:bg-orange-700"
                    }
                  >
                    {(result.similarity * 100).toFixed(2)}%
                  </Badge>
                </div>
                <Progress value={result.similarity * 100} className="h-3" />
              </div>

              <div className="space-y-2">
                <div className="text-sm">
                  <span className="font-medium">模型名称:</span> {result.model}
                </div>
                <div className="text-sm">
                  <span className="font-medium">向量维度:</span> {result.vector_dimension}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
              <div>
                <span className="font-medium">图片1特征范数:</span> {result.features1_norm?.toFixed(4)}
              </div>
              <div>
                <span className="font-medium">图片2特征范数:</span> {result.features2_norm?.toFixed(4)}
              </div>
              <div>
                <span className="font-medium">点积:</span> {result.dot_product?.toFixed(4)}
              </div>
            </div>

            {result.similarity < 0.95 && (
              <Alert>
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  相似度低于95%，可能的原因：
                  1. 图片内容不同
                  2. 图片在处理过程中发生变化（压缩、尺寸调整等）
                  3. 模型特征提取的局限性
                </AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
