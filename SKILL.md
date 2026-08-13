---
name: xiyou-asin-analysis
description: Use this skill when an Amazon seller needs to compare an owned ASIN with competitor ASINs, diagnose traffic or conversion decline, or identify a coverage, ranking, click, or conversion bottleneck from Xiyou exports and Amazon SP-API data. Do not use it for product-selection research, generic market sizing, or automatic advertising, Listing, promotion, or price changes.
---

# 西柚多 ASIN 竞品分析

## 核心原则

围绕具体业务问题运行“受理 → 体检 → 定向深挖 → 验证 → 行动 → 复盘”循环。让确定性脚本计算指标和证据链，让 Agent 解释信号，让人批准范围与动作。

开始前按需读取：

- 首次配置或缺凭据：读取 [SETUP.md](references/SETUP.md)。
- 接收文件或遇到字段异常：读取 [FIELD-CONTRACTS.md](references/FIELD-CONTRACTS.md)。
- 判断断点、置信度或质量门：读取 [DIAGNOSTIC-RULES.md](references/DIAGNOSTIC-RULES.md)。
- 操作西柚浏览器或 Amazon 报告：读取 [DATA-SOURCES.md](references/DATA-SOURCES.md)。

## 1. 任务受理与人工门①

拒绝把“出一份报告”当作业务问题。真实 Case 至少落成：站点、自身 ASIN、4–8 个分层竞品、周期、触发原因、要支持的决策、已知断货/促销/调价/变体事件。`cases/synthetic-case` 为最小回放，允许只含 2 个合成竞品，不适用于真实结论。

运行：

```bash
python scripts/create_case.py --output work/case.json --marketplace US \
  --own-asin B0SYNTH001 --competitor B0SYNTH002 --competitor B0SYNTH003 \
  --period-start 2026-01-01 --period-end 2026-01-30 \
  --objective "诊断自然流量下滑"
```

输出诊断计划：问题、范围、数据最小集、预期断点和缺口。要求人工门①确认竞品池、周期和问题；未确认时把 `competitor_review_status` 保持 `PENDING`，不得升级结论。

## 2. 快速体检

只取最便宜的数据：Amazon Sales and Traffic 与西柚多 ASIN 总览。首次运行先读 [SETUP.md](references/SETUP.md)，字段不匹配时读 [FIELD-CONTRACTS.md](references/FIELD-CONTRACTS.md)。

```bash
python scripts/fetch_amazon.py --case work/case.json --data-dir work/data
python scripts/ingest_xiyou.py --case work/case.json --data-dir work/data --file exports/xiyou.xlsx
python scripts/build_report.py --case work/case.json --data-dir work/data --output work/report.md
```

按固定顺序定位最早断点：覆盖 → 排名 → 点击 → 转化。报告必须同时输出 `*.diagnostics.json`、`*.quality-gates.json`、`*.claims.json`、`*.action-plan.json` 与 `*.review-plan.json`。

## 3. 定向深挖

只深挖已断的环节；每次取数先写目的。

| 断点 | 取数目的 | 入口 | 读取 |
|---|---|---|---|
| 覆盖 | 找出竞品覆盖而自身缺失的高相关词 | `scripts/ingest_xiyou.py` | `FIELD-CONTRACTS.md` |
| 排名 | 比较共同查询的自然位、SP 位与 Top10/20 | `scripts/ingest_xiyou.py` | `DIAGNOSTIC-RULES.md` |
| 点击 | 验证有曝光/排名但点击弱，比较主图、标题、价格、Coupon | `scripts/fetch_sqp.py`、`scripts/register_evidence.py` | `DATA-SOURCES.md` |
| 转化 | 验证点击后购买、流量精准度、评论主题、价格与库存 | `scripts/fetch_sqp.py`、`scripts/register_evidence.py` | `DIAGNOSTIC-RULES.md` |

已有 SQP reportId 时只运行：

```bash
python scripts/resume_sqp.py --case work/case.json --data-dir work/data \
  --report-id R123 --period-start 2026-01-04 --period-end 2026-01-10
```

## 4. 归因验证

让每条重要结论至少由两个独立来源方向一致地支持；同一西柚指标的两种表达不是独立证据。按 [DIAGNOSTIC-RULES.md](references/DIAGNOSTIC-RULES.md) 执行 G0–G7。

- L1：Amazon 后台/API 事实。
- L2：商品页、Seller Central 或运营事件的时点事实。
- L3：西柚估算和发现信号。
- L4：由证据形成的候选解释。

只有观察数据时写“相关、候选解释、待验证”，不写“导致、证明”。无法验证时明确缺什么、受影响的模块和恢复方式。

## 5. 输出行动与人工门②

再次运行 `scripts/build_report.py`。每项输出固定为：发现 → 候选原因 → 建议动作 → 风险 → 负责人 → 主指标 → 护栏 → 停止条件 → Evidence ID。

人工门②只选择最少必要动作。保持 `PENDING_HUMAN_REVIEW`，直到人明确批准。禁止脚本或 Agent 自动修改广告、Listing、价格、Coupon、促销或预算。

## 6. 复盘

动作批准后冻结 baseline。第 7、14、30 天回到步骤 2，使用同站点、同 ASIN、同口径重新体检；把同期断货、促销、调价、广告和变体变化单独登记。未执行动作时，复盘状态必须保持 `NOT_STARTED`。

## 硬性规则

1. 前置条件不满足时列出缺失项并停止对应结论；禁止用模拟数据冒充真实数据。
2. SQP 创建返回 reportId 后立即持久化。轮询超时只恢复该 reportId，禁止重复创建。
3. SQP 只请求 Case 内完整的周日至周六。Case 外周、跨周期周和部分周不得混入。
4. SQP `dataByAsin=[]` 表示官方报告可用但无可清洗行；不得解释为零曝光、零点击或权限失败。
5. SQP 部分周可用时标记 `PARTIAL_*`；不得外推到完整周期。
6. Sales and Traffic 同周期可能返回不同版本。保留全部原始版本；正式计算采用 `captured_at` 最新版本，不平均、不相加。
7. 同一 child ASIN 可能出现在多个 parent 分组。保留 parent 维度；只合计可加指标，并从总量重算比率；不得反推变体变更时间。
8. 西柚是 L3 估算。西柚流量份额不得写成 Amazon Sessions、CTR 或 CVR；西柚订单不得写成后台订单。
9. 西柚 7 天、1 个月和近 6 个月只作独立周期；禁止混算。月份范围/周平均不等于精确日边界，必须记录 period basis。
10. 西柚工作表 dimension 元数据可能错误；按真实非空区域重算。兼容“周搜索量/周平均搜索量”等官方表头别名。
11. 下载按钮或页面导出完成不等于文件已落盘。分别确认浏览器事件与最终文件，校验 XLSX ZIP 结构、大小和 SHA-256。
12. 重复导出先归档，再按 hash/语义判重。仅标签顺序变化的文件不得重复计入。
13. 前台库存与 Seller Central 库存冲突时只保留两个 L2 时点事实；不得据此推断整个报告期断货。
14. Ads API 缺权限时，把 CTR、CPC、CVR、ACOS/TACOS 标记缺失；禁止用自然流量或总销售额拼凑。
15. 每个数值保留 source level、站点、ASIN、周期、采集时间、原始路径、定位器、公式和 Evidence ID。
16. 凭据只从用户本地环境读取。禁止读取、导出或保存浏览器 Cookie；禁止把密码、Token、API Key 写入代码、日志、报告或 Case。
17. 只操作用户指定的西柚标签页。登录、验证码、2FA、授权或付费操作必须停下交还用户。
18. 竞品池与行动方案必须分别经过人工门①和人工门②。未审批时不执行。

## 验证

先用合成数据运行：

```bash
python scripts/smoke_test.py --work-dir .smoke
python scripts/validate_distribution.py
```

`smoke_test.py` 会把合成 JSON 生成临时 XLSX 并明确输出 `synthetic_data: true`；`--work-dir` 必须是新目录或空目录，脚本不会清空既有目录。真实 Case 完成前另行检查：原始 hash 全部一致；报告 Evidence ID 全部可解析；真实数据链中不存在 Mock/fixture 路径；缺失模块保持 `MISSING_DATA`、`REVIEW_REQUIRED` 或 `BLOCKED`。
