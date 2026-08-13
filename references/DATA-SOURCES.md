# 数据源与获取目的

## 何时读取

决定“这一步为什么取数”、判断权限降级或审查来源层级时读取。

| 数据源 | 层级 | 目的 | 典型字段 | 缺失时降级 |
|---|---|---|---|---|
| Amazon Sales and Traffic | L1 | 自身经营事实与总体转化 | Sessions、Page Views、Units、Sales | 无法验证真实流量与整体 CVR |
| Amazon SQP | L1 | 查询词级曝光、点击、购买 | impressions、clicks、purchases、shares | 点击/词级转化保持不可验证 |
| Amazon Ads API | L1/L2 | 广告效率 | impressions、clicks、spend、orders、sales | 不输出广告 CTR/CVR/CPC/ACOS/TACOS |
| 西柚总览导出 | L3 | 低成本竞品体检 | 流量得分、关键词数、估算订单、价格、评论 | 竞品规模和结构不可比较 |
| 西柚关键词导出 | L3 | 覆盖与排名定向深挖 | keyword、search volume、share、rank | 关键词 Gap 与位次不可诊断 |
| Listing/价格/评论快照 | L3 | 点击/转化假设佐证 | 主图、标题、价格、Coupon、Rating、Review | 不归因到页面或社会证明 |

## 西柚浏览器边界

- 只操作用户指定的西柚目标标签页。
- 不查看或枚举其他标签页。
- 不读取、复制或导出 Cookie。
- 优先使用官方导出，不用页面 DOM 抄数替代可下载文件。
- 遇到登录、验证码、2FA、API 授权或付费操作时停止并告诉用户。
- 下载完成必须以文件系统中的最终文件为准，并登记 SHA-256、周期和采集时间。

## Amazon Reports API 状态

创建、轮询和下载是三个不同阶段。持久化状态至少包含：

- report type
- report ID
- ASIN / marketplace
- requested period
- processing status
- last polled time
- document/artifact ID（成功后）
- failure reason（失败后）

只有成功下载并解析原始数据后，数据源才是 `AVAILABLE`。HTTP 成功、创建成功或 `IN_PROGRESS` 都不是数据可用。

## 取数最小化

快速体检只取 Sales and Traffic 与西柚总览；定位断点后才追加昂贵数据。每次追加数据前写明：

1. 要验证的假设。
2. 所需字段。
3. 来源与周期。
4. 成功/失败判据。
5. 权限缺失时的降级表述。
