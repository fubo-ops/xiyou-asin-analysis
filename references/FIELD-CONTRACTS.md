# 字段契约

## 何时读取

新增数据源、排查字段不兼容、审查指标口径或调整清洗逻辑时读取。

## CaseConfig

`case.json` 是一次诊断的边界，不包含凭据。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `case_id` | string | 是 | 稳定 Case 标识 |
| `run_id` | string | 否 | 同一 Case 的回放批次；默认等于 `case_id` |
| `marketplace` | string | 是 | 站点，例如 `US` |
| `own_asin` | string | 是 | 自身 ASIN，10 位大写字母数字 |
| `competitors` | array | 是 | 唯一且不与自身重复 |
| `period.start` | date | 是 | ISO 8601 |
| `period.end` | date | 是 | ISO 8601 |
| `objective` | string | 是 | 具体可诊断业务问题 |
| `lifecycle` | string | 否 | 生命周期；未知写 `unknown` |
| `competitor_review_status` | enum | 是 | `PENDING` / `APPROVED` |
| `event_history_status` | enum | 是 | `MISSING` / `CONFIRMED` |
| `known_events` | array | 否 | 断货、Deal、Coupon、调价、变体变化等已确认事件 |

## RawArtifact

每个原始文件登记后生成不可变 Artifact：

| 字段 | 说明 |
|---|---|
| `artifact_id` | 内容与元数据派生的稳定标识 |
| `source_name` | `XIYOU`、`AMAZON_SALES_TRAFFIC`、`AMAZON_SEARCH_QUERY_PERFORMANCE` 等 |
| `source_level` | `L1` 官方事实；`L2` 商家/广告官方来源；`L3` 第三方估算或页面观察 |
| `path` | 归档后的相对/运行时路径 |
| `metadata_path` | 来源、站点、ASIN、周期、采集时间、SHA-256 的 sidecar |
| `sha256` | 原始文件哈希 |
| `captured_at` | UTC ISO 8601 采集时间 |

## MetricRecord

统一长表是一行一个指标：

| 字段 | 说明 |
|---|---|
| `evidence_id` | Artifact、ASIN、指标、locator 的稳定哈希 |
| `artifact_id` | 反向连接 RawArtifact |
| `source_name` / `source_level` | 来源与事实层级 |
| `marketplace` / `asin` | 站点和对象 |
| `period_start` / `period_end` | 指标真实周期，不一定等于 Case 周期 |
| `metric` / `value` / `unit` | 规范化指标和值 |
| `locator` | XLSX 单元格或 API JSON Pointer |
| `raw_path` | 原始归档路径 |
| `captured_at` | 采集时间 |
| `dimensions` | keyword、parent ASIN、period basis 等维度 |
| `case_id` / `run_id` | Case 与回放批次 |

## Amazon Sales and Traffic 映射

| 原字段 | 统一指标 | 单位 |
|---|---|---|
| `salesByAsin.unitsOrdered` | `units_ordered` | count |
| `salesByAsin.totalOrderItems` | `total_order_items` | count |
| `salesByAsin.orderedProductSales.amount` | `ordered_product_sales` | currencyCode |
| `trafficByAsin.sessions` | `sessions` | count |
| `trafficByAsin.pageViews` | `page_views` | count |
| `trafficByAsin.sessionPercentage` | `session_percentage` | percent |
| `trafficByAsin.pageViewsPercentage` | `page_views_percentage` | percent |
| `trafficByAsin.buyBoxPercentage` | `buy_box_percentage` | percent |
| `trafficByAsin.unitSessionPercentage` | `unit_session_percentage` | percent |

同一 child ASIN 在多个 parent 分组出现时，只对可加指标求和；百分比不得相加，Unit Session % 必须用总 units ÷ 总 sessions 重算。

## Amazon SQP 映射

| 原字段 | 统一指标 |
|---|---|
| `searchQueryVolume` | `sqp_query_volume` |
| `impressionData.asinImpressionCount` | `sqp_impressions` |
| `impressionData.asinImpressionShare` | `sqp_impression_share` |
| `clickData.asinClickCount` | `sqp_clicks` |
| `clickData.asinClickShare` | `sqp_click_share` |
| `cartAddData.asinCartAddCount` | `sqp_cart_adds` |
| `purchaseData.asinPurchaseCount` | `sqp_purchases` |
| `purchaseData.asinPurchaseShare` | `sqp_purchase_share` |

`dataByAsin` 为空表示报告可下载但没有可清洗查询记录，不等于曝光、点击或购买为零。

## 西柚总览映射

| 可能表头 | 统一指标 | 语义 |
|---|---|---|
| 价格 | `xiyou_price` | 第三方页面/估算 |
| Review数量 | `xiyou_review_count` | 第三方观察 |
| Review评分 | `xiyou_review_rating` | 第三方观察 |
| 7天流量得分 / 流量得分 | `xiyou_7d_traffic_score` | 西柚得分，不是 Sessions |
| 流量得分（自然） | `xiyou_organic_traffic_score` | 西柚得分 |
| 流量得分（广告） | `xiyou_ad_traffic_score` | 西柚得分 |
| 近30天订单量等 | `xiyou_estimated_30d_orders` | 估算订单，不是后台订单 |
| 自然关键词数 | `xiyou_organic_keyword_count` | 估算覆盖 |
| 广告关键词数 | `xiyou_ad_keyword_count` | 估算覆盖 |

## 西柚关键词映射

每个关键词 × ASIN 生成 `xiyou_keyword_traffic_share`，其 `dimensions` 可包含：

- `keyword`
- `weekly_search_volume`
- `competitive_traffic_share`
- `traffic_share_of_asin`
- `organic_rank` / `organic_rank_page`
- `sp_ad_rank` / `sp_ad_rank_page`
- `placements`
- `relevance_score` / `relevance_tier`
- `period_basis`
- 每个字段的 `field_locators`

西柚“流量份额”不能替代 Amazon CTR；“点击转化率(均值)”不能替代自身 ASIN 的真实 CVR。

## 周期契约

- Case 周期决定分析边界。
- 7 天、1 个月、3 个月、6 个月、自定义导出必须分别登记，不混成同一周期。
- 每条指标采用其来源真实周期并记录 `period_basis`。
- SQP 只接受完整周日至周六。
- “近 30 天订单”若来源表选了更长周期，其指标周期仍按结束日回溯 30 天，并保留来源选择档位。
