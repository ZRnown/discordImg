"use client"

import { useState, useRef } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Plus, Trash2, Edit, Image as ImageIcon, Search, Upload, X } from "lucide-react"
import { toast } from "sonner"
import { Checkbox } from "@/components/ui/checkbox"

const mockRules: any[] = []

const availableAccounts = ["Sisyphus_Bot_01", "Marketing_Manager", "Auto_Responder_X", "Discord_Helper_04"]

export function RulesView() {
  const [rules, setRules] = useState(mockRules)
  const [isDialogOpen, setIsDialogOpen] = useState(false)
  const [editingRule, setEditingRule] = useState<any>(null)
  const [ruleSearch, setRuleSearch] = useState("")
  const [selectedAccountMode, setSelectedAccountMode] = useState("random")
  const [selectedSpecificAccounts, setSelectedSpecificAccounts] = useState<string[]>([])
  const [matchType, setMatchType] = useState("keyword")
  
  const [replyImage, setReplyImage] = useState<string | null>(null)
  const [triggerImage, setTriggerImage] = useState<string | null>(null)
  
  const replyImageInputRef = useRef<HTMLInputElement>(null)
  const triggerImageInputRef = useRef<HTMLInputElement>(null)

  const handleDeleteRule = (id: number) => {
    setRules((prev) => prev.filter((rule) => rule.id !== id))
    toast.success("规则已删除")
  }

  const handleEditRule = (rule: any) => {
    setEditingRule(rule)
    setSelectedAccountMode(rule.accountMode)
    setMatchType(rule.matchType)
    setSelectedSpecificAccounts(rule.assignedAccounts.includes("all") ? [] : rule.assignedAccounts)
    setReplyImage(rule.replyImage || null)
    setTriggerImage(rule.triggerImage || null)
    setIsDialogOpen(true)
  }

  const filteredRules = rules.filter(r => 
    r.keywords.some(k => k.toLowerCase().includes(ruleSearch.toLowerCase())) ||
    r.replyText.toLowerCase().includes(ruleSearch.toLowerCase())
  )

  const toggleAccountSelection = (acc: string) => {
    setSelectedSpecificAccounts(prev => 
      prev.includes(acc) ? prev.filter(a => a !== acc) : [...prev, acc]
    )
  }

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>, type: 'reply' | 'trigger') => {
    const file = e.target.files?.[0]
    if (file) {
      const reader = new FileReader()
      reader.onloadend = () => {
        if (type === 'reply') setReplyImage(reader.result as string)
        else setTriggerImage(reader.result as string)
        toast.success("图片已就绪")
      }
      reader.readAsDataURL(file)
    }
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-3xl font-bold tracking-tight">规则配置</h2>
          <p className="text-sm text-muted-foreground">配置自动回复触发规则、响应内容以及发送账号模式</p>
        </div>
        <div className="flex items-center gap-4">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="搜索规则关键词..."
              className="pl-9 w-[250px] h-10"
              value={ruleSearch}
              onChange={(e) => setRuleSearch(e.target.value)}
            />
          </div>
          <Dialog open={isDialogOpen} onOpenChange={(open) => {
            setIsDialogOpen(open)
            if (!open) {
              setEditingRule(null)
              setSelectedSpecificAccounts([])
              setReplyImage(null)
              setTriggerImage(null)
              setMatchType("keyword")
            }
          }}>
            <DialogTrigger asChild>
              <Button className="h-10 px-6 font-bold">
                <Plus className="mr-2 h-5 w-5" />
                添加新规则
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
              <DialogHeader>
                <DialogTitle className="text-2xl">{editingRule ? "编辑规则" : "创建新规则"}</DialogTitle>
                <DialogDescription>设置触发条件、回复内容及账号分配策略</DialogDescription>
              </DialogHeader>
              <div className="space-y-6 py-6">
                <div className="grid grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <Label className="font-bold text-sm">匹配模式</Label>
                    <Select value={matchType} onValueChange={setMatchType}>
                      <SelectTrigger className="h-10">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="keyword">关键词匹配 (Partial)</SelectItem>
                        <SelectItem value="exact">精确匹配 (Exact)</SelectItem>
                        <SelectItem value="regex">正则表达式 (Regex)</SelectItem>
                        <SelectItem value="image">图片识别 (识别特定照片)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  
                  <div className="space-y-2">
                    <Label className="font-bold text-sm">回复附件 (图片)</Label>
                    <input 
                      type="file" 
                      className="hidden" 
                      ref={replyImageInputRef} 
                      accept="image/*" 
                      onChange={(e) => handleImageUpload(e, 'reply')}
                    />
                    <div className="flex items-center gap-2">
                      {replyImage ? (
                        <div className="relative size-10 border rounded overflow-hidden group">
                          <img src={replyImage} className="object-cover w-full h-full" alt="Reply" />
                          <button 
                            onClick={() => setReplyImage(null)}
                            className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity"
                          >
                            <X className="size-4 text-white" />
                          </button>
                        </div>
                      ) : (
                        <Button 
                          variant="outline" 
                          className="w-full h-10 border-dashed justify-start text-muted-foreground"
                          onClick={() => replyImageInputRef.current?.click()}
                        >
                          <Upload className="mr-2 h-4 w-4" />
                          上传回复图片
                        </Button>
                      )}
                    </div>
                  </div>
                </div>

                {matchType === 'image' ? (
                  <div className="space-y-2 bg-primary/5 p-4 rounded-lg border-2 border-dashed border-primary/20">
                    <Label className="font-bold text-sm text-primary flex items-center gap-2">
                      <ImageIcon className="size-4" /> 识别目标 (触发照片)
                    </Label>
                    <input 
                      type="file" 
                      className="hidden" 
                      ref={triggerImageInputRef} 
                      accept="image/*" 
                      onChange={(e) => handleImageUpload(e, 'trigger')}
                    />
                    <p className="text-[11px] text-muted-foreground mb-3">当用户在 Discord 发送与此照片高度相似的图片时，将触发回复。</p>
                    {triggerImage ? (
                      <div className="relative w-full aspect-video border rounded-xl overflow-hidden group max-h-[200px]">
                        <img src={triggerImage} className="object-contain w-full h-full bg-black/10" alt="Trigger" />
                        <button 
                          onClick={() => setTriggerImage(null)}
                          className="absolute top-2 right-2 p-1 bg-red-500 rounded-full text-white shadow-lg"
                        >
                          <X className="size-4" />
                        </button>
                      </div>
                    ) : (
                      <Button 
                        variant="secondary" 
                        className="w-full h-24 flex-col gap-2"
                        onClick={() => triggerImageInputRef.current?.click()}
                      >
                        <Upload className="size-6" />
                        <span>点击上传识别模板图</span>
                      </Button>
                    )}
                  </div>
                ) : (
                  <div className="space-y-2">
                    <Label className="font-bold text-sm">触发条件 (关键词)</Label>
                    <Input 
                      id="keywords" 
                      defaultValue={editingRule ? editingRule.keywords.join(", ") : ""} 
                      placeholder="多个关键词用逗号分隔..." 
                      className="h-10" 
                    />
                  </div>
                )}

                <div className="space-y-2">
                  <Label className="font-bold text-sm">回复文字内容</Label>
                  <Textarea 
                    id="reply-text" 
                    defaultValue={editingRule ? editingRule.replyText : ""} 
                    placeholder="输入自动回复的文字（如果为空则只发图片）..." 
                    rows={4} 
                    className="text-base" 
                  />
                </div>

                <div className="grid grid-cols-2 gap-6 border-t pt-6">
                  <div className="space-y-2">
                    <Label className="font-bold text-sm">账号分配模式</Label>
                    <Select value={selectedAccountMode} onValueChange={setSelectedAccountMode}>
                      <SelectTrigger className="h-10">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="random">随机使用 (Random)</SelectItem>
                        <SelectItem value="rotation">顺序轮换 (Rotation)</SelectItem>
                        <SelectItem value="fixed">手动指定 (Specific)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label className="font-bold text-sm">选择执行账号</Label>
                    <div className="border rounded-md p-3 space-y-2 bg-muted/20 max-h-[150px] overflow-y-auto">
                      {availableAccounts.map(acc => (
                        <div key={acc} className="flex items-center space-x-2">
                          <Checkbox 
                            id={`acc-${acc}`} 
                            checked={selectedSpecificAccounts.includes(acc)}
                            onCheckedChange={() => toggleAccountSelection(acc)}
                          />
                          <label htmlFor={`acc-${acc}`} className="text-xs font-medium cursor-pointer">{acc}</label>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
              <DialogFooter className="border-t pt-6">
                <Button variant="outline" onClick={() => setIsDialogOpen(false)} className="h-10">
                  取消
                </Button>
                <Button
                  className="h-10 px-8 font-bold"
                  onClick={() => {
                    setIsDialogOpen(false)
                    toast.success("规则保存成功")
                  }}
                >
                  {editingRule ? "保存修改" : "确认添加规则"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      <Card className="shadow-sm">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/50 h-12">
                <TableHead className="text-sm font-bold pl-6">触发规则</TableHead>
                <TableHead className="text-sm font-bold">模式</TableHead>
                <TableHead className="text-sm font-bold">账号模式</TableHead>
                <TableHead className="text-sm font-bold">回复内容</TableHead>
                <TableHead className="text-sm font-bold">延迟</TableHead>
                <TableHead className="text-sm font-bold text-right pr-6">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredRules.map((rule) => (
                <TableRow key={rule.id} className="h-16 hover:bg-muted/30 transition-colors">
                  <TableCell className="pl-6">
                    {rule.matchType === 'image' ? (
                      <div className="flex items-center gap-2">
                        <div className="size-8 rounded border bg-muted overflow-hidden">
                          {rule.triggerImage ? <img src={rule.triggerImage} className="object-cover w-full h-full" alt="Trigger" /> : <ImageIcon className="size-4 m-2 text-muted-foreground" />}
                        </div>
                        <Badge variant="outline" className="text-[10px] bg-blue-50 text-blue-700">图片匹配</Badge>
                      </div>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {rule.keywords.map((keyword, i) => (
                          <Badge key={i} variant="secondary" className="text-[11px] font-medium h-5 bg-orange-50 text-orange-700 border-orange-200">
                            {keyword}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className="text-[11px] font-medium h-5 border-primary/20 text-primary">
                      {rule.matchType === "keyword" && "关键词"}
                      {rule.matchType === "exact" && "精确匹配"}
                      {rule.matchType === "regex" && "正则"}
                      {rule.matchType === "image" && "图片识别"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge className={`${rule.accountMode === 'rotation' ? "bg-purple-600" : "bg-blue-600"} text-[11px] h-5`}>
                      {rule.accountMode === "random" ? "随机使用" : rule.accountMode === "rotation" ? "自动轮换" : "固定账号"}
                    </Badge>
                  </TableCell>
                  <TableCell className="max-w-[200px]">
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] truncate font-medium">{rule.replyText || "(仅回复图片)"}</span>
                      {rule.replyImage && <span className="text-[9px] text-blue-500 flex items-center font-bold"><ImageIcon className="size-3 mr-1" /> [附带图片回复]</span>}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs font-mono font-bold">{rule.min_delay}-{rule.max_delay}s</TableCell>
                  <TableCell className="text-right pr-6">
                    <div className="flex items-center justify-end gap-2">
                      <Button variant="ghost" size="icon" className="h-9 w-9" onClick={() => handleEditRule(rule)}>
                        <Edit className="size-4" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-9 w-9 hover:bg-red-50 hover:text-red-600" onClick={() => handleDeleteRule(rule.id)}>
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {filteredRules.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="h-24 text-center text-muted-foreground italic">未找到符合搜索条件的规则</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
