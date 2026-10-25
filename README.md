# 西柚多 ASIN 竞品分析

## 一眼看懂

- 这是什么：对比自家 ASIN 和竞品的流量与转化，找出问题环节。
- 什么时候用：自家 ASIN 自然流量或转化突然下滑，要查原因时。
- 给它什么：西柚导出表、亚马逊后台报告和竞品清单。
- 它给你什么：一份带数据出处的报告，指出断点和下一步动作。

## 项目简介

`xiyou-asin-analysis` 是一个 Amazon 多 ASIN 竞品分析 Agent Skill，配套 Python 命令行工具。输入自身 ASIN、竞品池、分析周期、西柚官方导出和 Amazon SP-API 报告，按“覆盖 → 排名 → 点击 → 转化”定位问题，生成带证据引用的 Markdown 报告。

仓库把确定性计算和语义判断分开：Python 脚本负责文件归档、指标清洗、诊断规则和报告生成，[SKILL.md](SKILL.md) 规定 Agent 的取数顺序、人工确认和行动评审。脚本不会自动修改广告、Listing、价格或促销。

## 核心功能

- 🧭 **漏斗定位**：覆盖、排名、点击、转化
- 🗂️ **Case 管理**：站点、竞品、周期与问题
- 📊 **西柚导入**：清洗总览与关键词表
- ☁️ **Amazon 取数**：Sales/Traffic 与 SQP
- ♻️ **SQP 续跑**：按 reportId 恢复原报告
- 🧾 **证据留痕**：SHA-256、定位器与 ID
- 📝 **报告输出**：Markdown 报告与五个 JSON

## 技术栈

| 层级 | 技术 | 版本 |
| --- | --- | --- |
| 语言 | Python（argparse + 标准库） | >=3.12 |
| Excel 读取 | openpyxl | >=3.1,<4 |
| HTTP 请求 | requests | >=2.32,<3 |
| 测试 | pytest | >=8.3,<9 |
| 构建 | setuptools | — |
| CI | GitHub Actions（Windows） | — |

版本取自 `requirements.txt` 与 `pyproject.toml`，仓库没有依赖锁文件。setuptools 只声明 `>=75`、CI 的 Python 版本写在工作流里，两者都无可比版本号，记「—」。

## 快速开始

需要 Python 3.12+ 和 Git，Windows、macOS、Linux 均可；只跑合成回放不需要账号或浏览器，取真实 Amazon 数据需要已注册的 SP-API 应用与卖家授权。以下命令在仓库根目录执行，尖括号占位符请替换成真实值。

1. 克隆仓库，建虚拟环境并安装依赖

   ```bash
   git clone https://github.com/fubo-ops/xiyou-asin-analysis.git
   cd xiyou-asin-analysis
   python -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

2. 先跑不联网的合成回放和分发自检，确认环境可用

   ```bash
   python scripts/smoke_test.py --work-dir .smoke-run
   python scripts/validate_distribution.py
   ```

3. 生成本机 `.env`，按接入说明填写 SP-API 配置

   ```bash
   cp .env.example .env
   ```

4. 从西柚官方页面下载对应周期的 XLSX，并创建 Case（ASIN 与日期仅为占位）

   ```bash
   python scripts/create_case.py --output .runtime/case.json --marketplace US --own-asin <OWN_ASIN> --competitor <COMP_ASIN_1> --competitor <COMP_ASIN_2> --period-start 2026-01-01 --period-end 2026-01-30 --objective "定位自然流量下滑的最早漏斗断点"
   ```

5. 导入西柚导出、取 Amazon 报告，生成 Markdown 报告与 JSON 补充

   ```bash
   python scripts/ingest_xiyou.py --case .runtime/case.json --data-dir .runtime/data --file <XIYOU_XLSX> --source-period-start 2026-01-01 --source-period-end 2026-01-30 --period-basis official_export_selected_1m
   python scripts/fetch_amazon.py --case .runtime/case.json --data-dir .runtime/data
   python scripts/build_report.py --case .runtime/case.json --data-dir .runtime/data --output .runtime/report.md
   ```

6. 已有 SQP `reportId` 时只做恢复，不重复创建报告

   ```bash
   python scripts/resume_sqp.py --case .runtime/case.json --data-dir .runtime/data --report-id <REPORT_ID> --period-start 2026-01-04 --period-end 2026-01-10
   ```

第 4 步之后仍需按 Skill 流程确认竞品池、周期和业务问题；建议动作要经人工评审。真实 Case、原始导出、报告和凭据都保存在被 Git 忽略的运行目录里。

## 项目结构

只列两层，完整文件清单见文末《详细说明》。

```text
xiyou-asin-analysis/
├── .github/                            # CI 工作流
├── assets/                             # 报告模板
├── cases/                              # 合成 Case 样例
├── docs/                               # 归档设计文档
├── references/                         # 数据源、诊断规则与字段契约
├── scripts/                            # CLI 入口脚本
│   └── xiyou_skill/                    # 唯一的实现包
├── tests/                              # 单元测试与仓库契约测试
├── tools/                              # 阶段二验证脚本
├── .env.example                        # SP-API 环境变量样例
├── LICENSE                             # MIT 许可证
├── SKILL.md                            # Skill 入口与流程
├── pyproject.toml                      # 项目元数据与 pytest 配置
└── requirements.txt                    # Python 依赖
```

## 架构图

原始数据保留版本和证据定位，报告按来源、周期与质量门决定哪些结论可以输出：

```text
【任务与数据接入】
┌────────────────────────────────────────────┐
│   业务问题 + 自身 ASIN + 4–8 个竞品 + 周期 │
└──────────────────────┬─────────────────────┘
                       ▼
┌────────────────────────────────────────────┐
│   create_case.py → Case JSON（竞品池待确认）│
└──────────────────────┬─────────────────────┘
                       ▼
┌───────────────┬───────────────┬────────────┐
│ 西柚官方 XLSX │ Amazon 报告   │ SP-API     │
└───────┬───────┴───────┬───────┴─────┬──────┘
        ▼               ▼             ▼
┌────────────────────────────────────────────┐
│ ingest_xiyou / ingest_amazon / fetch_amazon │
│ fetch_sqp / resume_sqp                     │
└──────────────────────┬─────────────────────┘
                       ▼
┌────────────────────────────────────────────┐
│   原始文件 + SHA-256 + Evidence ID 归档     │
└──────────────────────┬─────────────────────┘
                       ▼
┌────────────────────────────────────────────┐
│   标准化 JSONL 与来源状态                   │
└──────────────────────┬─────────────────────┘
                       ▼
┌────────────────────────────────────────────┐
│   诊断规则：覆盖 → 排名 → 点击 → 转化       │
└──────────────────────┬─────────────────────┘
                       ▼
┌────────────────────────────────────────────┐
│   Markdown 报告 + 五个 JSON sidecar         │
│   diagnostics / quality-gates / claims      │
│   action-plan / review-plan                │
└──────────────────────┬─────────────────────┘
                       ▼
┌────────────────────────────────────────────┐
│   人工门②：评审行动与复盘计划               │
└────────────────────────────────────────────┘
```

命令行入口通过 `scripts/_runner.py` 调用唯一实现包 `scripts/xiyou_skill/`；`.env`、`work/`、运行数据和报告都不提交到 Git。

## 开发计划

### Phase 1: 任务与数据接入

- ✅ Case 创建（站点、竞品、周期、业务问题）
- ✅ 西柚 XLSX 导入与指标清洗
- ✅ Amazon Sales and Traffic 导入与 SP-API 获取

### Phase 2: 诊断与证据

- ✅ 覆盖 → 排名 → 点击 → 转化漏斗诊断
- ✅ SQP 完整周取数与 `reportId` 恢复
- ✅ 原始文件 SHA-256、定位器与 Evidence ID 归档

### Phase 3: 报告与评审

- ✅ Markdown 报告与五个 JSON sidecar
- ✅ 质量门、结论与行动评审输出
- ✅ 合成 Case 离线回放

### Phase 4: 工程化

- ✅ GitHub Actions（Windows，pytest + 回放 + 分发检查）
- ✅ 仓库分发契约测试
- ⬜ 真实业务验收记录
- ⬜ 后续功能排期与发布里程碑

## 文档

- [Skill 入口](SKILL.md)、[接入说明](references/SETUP.md)
- [数据源](references/DATA-SOURCES.md)、[字段契约](references/FIELD-CONTRACTS.md)
- [诊断规则](references/DIAGNOSTIC-RULES.md)、[报告模板](assets/report-template.md)
- [合成 Case](cases/synthetic-case/case.json)、[CI 配置](.github/workflows/verify.yml)
- [单一源码迁移设计（归档）](docs/archive/2026-08-13-single-source-repository-design.md)、[迁移执行计划（归档）](docs/archive/2026-08-13-single-source-repository.md)

## 许可证

[MIT License](LICENSE)，Copyright (c) 2026 fubo-ops。

---

原 README 里的环境要求、安装与 Skill 部署、完整命令、数据边界、全部已跟踪文件清单与当前状态等细节，已全部迁移到 [docs/详细说明.md](docs/详细说明.md)。
