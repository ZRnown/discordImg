import type { Placement } from "react-joyride"

export type TutorialStep = {
  id: string
  view: string
  title: string
  description: string
  selector: string
  note?: string
  label?: string
  alert?: string
  shape?: "pill" | "card" | "ring" | "diamond" | "arc"
  tone?: "cyan" | "emerald" | "amber" | "violet" | "rose" | "slate"
  placement?: Placement
  spotlightPadding?: number
}

const introSteps: TutorialStep[] = [
  {
    id: "sidebar",
    view: "dashboard",
    title: "从这里开始",
    description: "点击左侧的新手教程后，系统会按顺序带你切页面。前面几步先帮你建立整体路径，后面再详细讲规则怎么配。",
    selector: "[data-tutorial='sidebar-tutorial']",
    label: "入口",
    alert: "教程会自动切页，但不会替你保存任何配置。",
    shape: "pill",
    tone: "cyan",
    placement: "right",
    spotlightPadding: 12,
  },
  {
    id: "dashboard",
    view: "dashboard",
    title: "仪表盘只看总览",
    description: "这里先看系统是不是活着，店铺、商品、图片和回复数量大概是什么情况。真正配置和抓取，不在这一页做。",
    selector: "[data-tutorial='dashboard-root']",
    label: "总览",
    alert: "这一步只确认状态，不建议在这里停太久。",
    shape: "card",
    tone: "slate",
    placement: "bottom",
  },
]

const adminLeadSteps: TutorialStep[] = [
  {
    id: "shops",
    view: "shops",
    title: "先做店铺管理",
    description: "第一步先把微店店铺收进系统，确认店铺 ID、名称和列表都对。店铺没建好，后面的商品抓取就没有稳定入口。",
    selector: "[data-tutorial='shops-add-shop']",
    label: "店铺管理",
    alert: "店铺页负责维护抓取来源，先有店铺，后有商品。",
    shape: "card",
    tone: "emerald",
    placement: "right",
    note: "只有管理员能看到这一页。",
  },
]

const operationSteps: TutorialStep[] = [
  {
    id: "scraper",
    view: "scraper",
    title: "然后去做微店抓取",
    description: "这里才是把微店商品、图片和链接真正抓进系统的地方。常见顺序是先选店铺，再启动抓取，再看抓取数量、重复数和失败原因是否正常。",
    selector: "[data-tutorial='scraper-main']",
    label: "微店抓取",
    alert: "店铺页管来源，抓取页管把商品和图片拉进库。",
    shape: "diamond",
    tone: "cyan",
    placement: "left",
  },
  {
    id: "accounts-global",
    view: "accounts",
    title: "账号页先定全局默认值",
    description: "进入账号与规则页后，先看这里的全局设置。相似度阈值、回复延迟、关键词命中上限都会先用这里的默认值，网站级设置只有在你单独填写时才覆盖它。",
    selector: "[data-tutorial='accounts-global-settings']",
    label: "全局规则",
    alert: "建议先把全局值调到大致可用，再去做单网站微调。",
    shape: "card",
    tone: "violet",
    placement: "top",
  },
  {
    id: "accounts-delay",
    view: "accounts",
    title: "回复延迟决定发送节奏",
    description: "这里控制机器人每次回复前随机等待多久。数值越小，回复越快；数值越大，行为越保守。现在默认是 1 到 3 秒，如果你担心过快，可以拉到 2 到 5 秒；如果更强调即时反馈，可以压到 1 到 2 秒。",
    selector: "[data-tutorial='accounts-delay-settings']",
    label: "延迟",
    alert: "这是全局默认延迟，后面某个网站如果单独填了，会优先使用网站值。",
    shape: "pill",
    tone: "cyan",
    placement: "top",
  },
  {
    id: "accounts-keyword-limit",
    view: "accounts",
    title: "关键词命中上限用来拦多词刷屏",
    description: "这里控制一条消息里命中多少个不同关键词后直接不回复。比如你设成 2，消息里同时出现 B30、B22、B44，这条就会被拦掉。`0` 表示不限制，适合词比较干净的场景；想更保守，就把它设成 2 或 3。",
    selector: "[data-tutorial='accounts-keyword-limit']",
    label: "关键词上限",
    alert: "这个值非常适合拦同一句话里塞很多货号的消息。",
    shape: "ring",
    tone: "amber",
    placement: "top",
  },
]

const adminWebsiteSteps: TutorialStep[] = [
  {
    id: "accounts-add-website",
    view: "accounts",
    title: "网站模板从这里加",
    description: "店铺和商品都进系统后，再在这里绑定回复网站。优先选内置模板，比如微店、Kakobuy、OOPBuy 这类。同一个模板可以重复添加，区别只靠显示名称，比如“微店2”“Kakobuy-备用”。",
    selector: "[data-tutorial='accounts-add-website']",
    label: "网站模板",
    alert: "这里先讲入口，不再带你进弹窗，避免教程因为弹窗目标丢失而跳步。",
    shape: "card",
    tone: "amber",
    placement: "bottom",
  },
]

const ruleDetailSteps: TutorialStep[] = [
  {
    id: "accounts-websites-list",
    view: "accounts",
    title: "每个网站都在这里单独管理",
    description: "网站列表是整套规则真正生效的地方。你会在这里给网站绑定频道、绑定发送账号、选择回复模式，再决定这个网站是否要覆盖全局阈值和延迟。全局设置只是默认值，网站列表才是具体落地。",
    selector: "[data-tutorial='accounts-websites-list']",
    label: "网站列表",
    alert: "真正上线前，至少要看一遍每个网站这一行的配置。",
    shape: "card",
    tone: "slate",
    placement: "left",
  },
  {
    id: "accounts-website-threshold",
    view: "accounts",
    title: "相似度阈值决定图搜有多严格",
    description: "这个值越高，只有更像的图片才会命中；越低，结果会更宽松。货图比较干净、同款图很多时，可以适当调高；噪声比较大、用户图拍得乱时，可以略微调低。留空就继承全局，只对当前网站单独填写时才覆盖。",
    selector: "[data-tutorial='accounts-website-threshold']",
    label: "图搜阈值",
    alert: "如果某个网站误命中明显偏多，就优先先调它，不要急着改全局。",
    shape: "arc",
    tone: "rose",
    placement: "top",
    spotlightPadding: 16,
  },
  {
    id: "accounts-website-delay",
    view: "accounts",
    title: "网站级回复延迟会覆盖全局延迟",
    description: "这里是当前网站自己的回复节奏。你给它填了值，这个网站就不再用全局延迟；留空则继续继承全局。常见做法是把主要站点设得更稳一些，把测试站点设得更快一些，这样不用为了一个网站去动整套全局节奏。",
    selector: "[data-tutorial='accounts-website-delay']",
    label: "单站延迟",
    alert: "这块只影响当前网站，适合做保守站点和激进站点的分层。",
    shape: "pill",
    tone: "emerald",
    placement: "top",
  },
  {
    id: "accounts-website-keyword-limit",
    view: "accounts",
    title: "网站级关键词上限用来处理单站噪声",
    description: "如果某个网站特别容易被多关键词消息刷屏，就给它单独设上限。比如全局是 `0` 不限制，但某个网站你设成 `2`，那它遇到一条消息里命中 3 个不同关键词时，就只跳过这个网站，不影响别的网站继续判断。",
    selector: "[data-tutorial='accounts-website-keyword-limit']",
    label: "单站上限",
    alert: "这里最适合处理单个网站的噪声环境，不用一刀切改全局。",
    shape: "ring",
    tone: "amber",
    placement: "top",
  },
  {
    id: "accounts-message-filters",
    view: "accounts",
    title: "过滤规则负责先拦掉不该回复的消息",
    description: "这一块是整套系统最细的规则层。常见用法包括：拦包含某段文本的消息、拦开头或结尾固定格式、用正则拦特定模式、拦图片消息、拦某个用户或身份组、拦参考图相似的噪声图、拦数字超范围的尺码消息、拦同一用户短时间重复发送。全局过滤会影响所有网站，网站里的过滤只影响当前网站。",
    selector: "[data-tutorial='accounts-message-filters']",
    label: "过滤规则",
    alert: "理解成“先过滤，再识别，再决定回不回”会最清楚。",
    shape: "pill",
    tone: "emerald",
    placement: "right",
  },
  {
    id: "image-search",
    view: "image-search",
    title: "最后用图搜图页面做自检",
    description: "当店铺、商品、网站和规则都配好以后，就来这里做最终验证。上传一张真实用户图，看看能不能稳定命中目标商品，再结合你刚才设置的阈值判断是否需要继续微调。",
    selector: "[data-tutorial='image-search-upload']",
    label: "验证",
    alert: "这一步最适合验证“规则有没有太松或太严”。",
    shape: "ring",
    tone: "violet",
    placement: "left",
  },
]

const adminTailSteps: TutorialStep[] = [
  {
    id: "logs",
    view: "logs",
    title: "有问题就回到日志页排查",
    description: "如果你发现没有回复、命中了却没发、或者抓取异常，日志页是最后的核查点。先看它有没有识别到消息，再看有没有被过滤、有没有因为阈值不够被拦、有没有因为发送链路异常失败。",
    selector: "[data-tutorial='logs-controls']",
    label: "日志",
    alert: "教程走完后，日志页通常是最常回来的页面。",
    shape: "arc",
    tone: "slate",
    placement: "top",
    note: "只有管理员能看到这一页。",
  },
]

export function buildTutorialSteps(isAdmin: boolean): TutorialStep[] {
  const steps: TutorialStep[] = [...introSteps]

  if (isAdmin) {
    steps.push(...adminLeadSteps)
  }

  steps.push(...operationSteps)

  if (isAdmin) {
    steps.push(...adminWebsiteSteps)
  }

  steps.push(...ruleDetailSteps)

  if (isAdmin) {
    steps.push(...adminTailSteps)
  }

  steps.push({
    id: "finish",
    view: "dashboard",
    title: "教程结束",
    description: "以后你实际操作时，就按这条顺序走：先店铺管理，再微店抓取，再到账号与规则页绑定网站、频道和发送账号，最后用图搜图与日志做验证。",
    selector: "[data-tutorial='sidebar-tutorial']",
    label: "完成",
    alert: "你可以随时再点一次新手教程重新跑一遍。",
    shape: "pill",
    tone: "cyan",
    placement: "right",
  })

  return steps
}
