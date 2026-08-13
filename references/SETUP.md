# SETUP：真实数据接入

## 何时读取

在人工门①确认范围后、第一次采集真实数据之前读取。若只运行合成 smoke test，可跳过本文件。

## Amazon SP-API

### 所需授权

1. Selling Partner API 开发者账号。
2. 已注册并可调用 Reports API 的应用。
3. 目标卖家对该应用完成授权后得到的 LWA refresh token。
4. 目标站点 marketplace ID。

LWA client ID 与 client secret 本身不能替代卖家授权的 refresh token。没有 refresh token 时，CLI 必须报缺失并停止。

### 本地配置

从仓库根目录复制 `.env.example` 为 `.env`，只在本机填写：

```dotenv
SP_API_LWA_CLIENT_ID=
SP_API_LWA_CLIENT_SECRET=
SP_API_REFRESH_TOKEN=
SP_API_MARKETPLACE_ID=ATVPDKIKX0DER
SP_API_ENDPOINT=https://sellingpartnerapi-na.amazon.com
```

`.env` 已被 `.gitignore` 排除。禁止把真实值写入 README、Case JSON、命令行历史、日志或测试 fixture。

### Sales and Traffic

入口：

```bash
python scripts/fetch_amazon.py --case case.json --data-dir data
```

报告类型为 `GET_SALES_AND_TRAFFIC_REPORT`。同一周期多次拉取可能产生不同版本；所有版本都保留，分析默认采用 `captured_at` 最新版本，且不跨版本相加。

### SQP

入口：

```bash
python scripts/fetch_sqp.py --case case.json --data-dir data
```

SQP 只请求 Case 内完整的周日至周六。创建成功后必须立即把 `reportId` 持久化。轮询超时或程序中断后使用：

```bash
python scripts/resume_sqp.py --case case.json --data-dir data --report-id REPORT_ID --period-start YYYY-MM-DD --period-end YYYY-MM-DD
```

不得为同一站点、ASIN、周期重复创建报告。

## 西柚官方导出

1. 在已登录的浏览器会话中打开目标多 ASIN 对比页。
2. 只操作该目标标签页，不查看其他标签页。
3. 在关键词列表选择与 Case 一致的时间档位，再点击“下载”。
4. 等浏览器下载完成后，从下载目录取得最终 XLSX；“点击下载”或前端提示不是成功证据。
5. 用入口登记：

```bash
python scripts/ingest_xiyou.py --case case.json --data-dir data --file path/to/export.xlsx --source-period-start YYYY-MM-DD --source-period-end YYYY-MM-DD --period-basis official_export_selected_1m
```

若页面要求登录、验证码、2FA、授权或付费，停止并告诉用户。禁止导出 Cookie 或把登录态复制到代码。

## 可选数据源

- SQP 缺失：覆盖和排名仍可使用西柚估算完成；点击/查询词级转化只能标记不可验证。
- Ads API 缺失：广告 CTR、CVR、CPC、ACOS、TACOS 保持缺失。
- Listing/价格/评论快照缺失：不得把点击或转化差距归因到主图、价格、Coupon 或评论。

## 原始数据目录

CLI 会在 `--data-dir` 下保存原始文件、元数据、标准化 JSONL、来源状态和报告 sidecar。对外分享报告前，必须单独判断原始数据是否允许分享；本公开仓库不得接收真实 Case 数据。
