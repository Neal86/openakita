# OpenAkita 财务自动化插件 — M1 W2 完成报告

| 项目 | 值 |
|---|---|
| 文档版本 | v1.0 |
| 报告日期 | 2026-05-23 |
| 主开发者 | Cursor agent (Claude 4.7 Opus) |
| 设计来源 | `_finance_plugin_design_v0.3_INDEX.md` §6 W2 任务清单 |
| 工作分支 | `revamp/v3-orgs` (8 个 W2 commit 全部本地，未 push) |
| Schema | v1 → **v4** |
| 测试 | **55 / 55 通过**（pytest）|
| E2E | **7 / 7 步通过**（`m1_w2_acceptance.py`）|

---

## 1. 各 Stage 完成度

| Stage | 主题 | 完成度 | 备注 |
|:-:|---|:-:|---|
| 1 | KeyManager 真实加密 | ✅ | AES-256-GCM、PBKDF2-SHA256、OS keyring + env 兜底；`migrate-encrypt` CLI |
| 2 | Renderer 抽象 + benchmark | ✅ | xltpl + openpyxl 双轨，benchmark 报告 7.4 KB |
| 3 | 双准则 YAML 模板 | ✅ | 4 份 YAML（小企业/企业准则各 BS+PL），`extends` 继承；3 个 TBD |
| 4 | 报表生成 API + cell-level 追溯 | ✅ | 4 端点，AST 沙箱化公式器，`reports`/`report_cells` 表 |
| 5 | 增值税申报表 parser | ✅ | 金税四期通用模板，省份探针 ≥ 7 省，`vat_declarations` 表 |
| 6 | 审计模板上传 + Jinja2 校验 | ✅ | 3 端点，placeholder 扫描+严格模式渲染，`audit_templates` 表 |
| 7 | 端到端验收脚本 | ✅ | 7 步全 2xx，trial_balance_rows 100% 密文 |
| 8 | 完成报告 | ✅ | 本文 |

---

## 2. 8 个 commit 摘要

| # | SHA | Title |
|--:|---|---|
| 1 | `0ad4e6d6` | feat(finance-auto): integrate AES-256-GCM field encryption with OS keyring |
| 2 | `669890df` | feat(finance-auto): add ReportRenderer abstraction with xltpl/openpyxl dual-track |
| 3 | `a7cca59f` | feat(finance-auto): add YAML report templates for both small and general accounting standards |
| 4 | `c7f632d7` | feat(finance-auto): implement report generation pipeline with cell-level traceability |
| 5 | `d764d8d9` | feat(finance-auto): add VAT declaration parser for golden tax IV format |
| 6 | `015f0942` | feat(finance-auto): add audit template upload with placeholder validation |
| 7 | `26b6ef72` | test(finance-auto): add M1 W2 end-to-end acceptance script |
| 8 | (this commit) | docs(finance-auto): add M1 W2 completion report |

> Stage 1 的 commit 同时把 W1 阶段的 vertical slice scaffold（5 张表 + 6
> 路由 + 三层 .xls 解析器）一起带入了 git —— 这部分代码 W1 完成时本地可
> 跑但还没有 commit。Stage 1 commit body 里有完整说明。

---

## 3. 新增 / 修改文件清单

### 3.1 新增（W2）

```
plugins/finance-auto/
├── README.md                                       (W1 baseline, 入 git)
├── __init__.py                                     (W1 baseline, 入 git)
├── _e2e_run.py                                     (W1 baseline, 入 git)
├── plugin.json                                     (W1 baseline, 入 git)
├── plugin.py                                       (W1 baseline, 入 git)
├── finance_auto_backend/
│   ├── __init__.py                                 (W1 baseline)
│   ├── audit_routes.py                             ★ Stage 6
│   ├── db.py                                       (W1; Stage 4 加 migration)
│   ├── encryption.py                               ★ Stage 1
│   ├── key_manager.py                              ★ Stage 1
│   ├── key_meta.py                                 ★ Stage 1
│   ├── models.py                                   (W1; Stage 4-6 扩充)
│   ├── normalizers/account_code.py                 (W1)
│   ├── parsers/
│   │   ├── xls_parser.py                           (W1)
│   │   └── vat_declaration.py                      ★ Stage 5
│   ├── report_generator.py                         ★ Stage 4
│   ├── report_routes.py                            ★ Stage 4
│   ├── routes.py                                   (W1; Stage 1/4/5/6 扩充)
│   ├── schema.py                                   (W1; Stage 4/5/6 加 DDL)
│   ├── vat_routes.py                               ★ Stage 5
│   ├── config/
│   │   ├── __init__.py                             ★ Stage 3
│   │   └── yaml_loader.py                          ★ Stage 3
│   ├── renderers/
│   │   ├── __init__.py                             ★ Stage 2
│   │   ├── base.py                                 ★ Stage 2
│   │   ├── factory.py                              ★ Stage 2
│   │   ├── openpyxl_writer.py                      ★ Stage 2
│   │   └── xltpl_renderer.py                       ★ Stage 2
│   └── services/
│       ├── __init__.py                             ★ Stage 6
│       └── audit_template.py                       ★ Stage 6
├── scripts/
│   ├── __init__.py                                 ★ Stage 1
│   ├── benchmark_renderers.py                      ★ Stage 2
│   ├── m1_w2_acceptance.py                         ★ Stage 7
│   └── migrate_encrypt.py                          ★ Stage 1
├── templates/reports/
│   ├── balance_sheet_general_enterprise.yaml       ★ Stage 3
│   ├── balance_sheet_small_enterprise.yaml         ★ Stage 3
│   ├── income_statement_general_enterprise.yaml    ★ Stage 3
│   └── income_statement_small_enterprise.yaml      ★ Stage 3
└── tests/
    ├── __init__.py                                 ★ Stage 1
    ├── conftest.py                                 ★ Stage 1
    ├── test_audit_template.py                      ★ Stage 6 (5 cases)
    ├── test_encryption_integration.py              ★ Stage 1 (3 cases)
    ├── test_key_manager.py                         ★ Stage 1 (16 cases)
    ├── test_renderers.py                           ★ Stage 2 (8 cases)
    ├── test_report_api.py                          ★ Stage 4 (1 case)
    ├── test_report_generator.py                    ★ Stage 4 (7 cases)
    ├── test_vat_declaration.py                     ★ Stage 5 (6 cases)
    └── test_yaml_loader.py                         ★ Stage 3 (9 cases)
```

★ = W2 新增；`(W1 baseline)` = W1 阶段已完成、Stage 1 commit 时入 git。

### 3.2 修改（含 W1 baseline）

| 文件 | 谁改 | 备注 |
|---|---|---|
| `plugins/finance-auto/finance_auto_backend/schema.py` | Stage 1/4/5/6 | SCHEMA_VERSION 1 → 4，加 4 张新表 + MIGRATION_STEPS |
| `plugins/finance-auto/finance_auto_backend/db.py` | Stage 1/4 | KeyManager 接入；增量 migration 重放 |
| `plugins/finance-auto/finance_auto_backend/models.py` | Stage 1/4/5/6 | Report*, Vat*, AuditTemplate Pydantic 模型 |
| `plugins/finance-auto/finance_auto_backend/routes.py` | Stage 1/4/5/6 | 加密透写/读、`list_all_rows`、注册新端点族 |
| `plugins/finance-auto/finance_auto_backend/plugin.py` | Stage 1 | 启动时 `auto_unlock_if_configured()` |
| `plugins/finance-auto/_e2e_run.py` | Stage 1 | 同上，让 e2e harness 也开加密 |
| `.gitignore` | Stage 4 | 加白名单：`!plugins/**/test_report_*.py` |

### 3.3 设计/报告文件

| 文件 | 大小 | 说明 |
|---|--:|---|
| `_m1_w2_xltpl_benchmark.md` | 7.4 KB | Stage 2 三路径 benchmark 报告 |
| `_m1_w2_bench.json` | ~1.8 KB | benchmark 原始 JSON |
| `_m1_w2_acceptance_result.json` | ~1 KB | Stage 7 端到端运行结果 |
| `_m1_w2_completion_report.md` | 本文 | Stage 8 |

---

## 4. API 总数

W1 已有 5 个 + W2 新增 9 个 = **14 个 API**：

| # | 阶段 | Method | 路径 | 说明 |
|--:|:-:|:-:|---|---|
| 1 | W1 | POST | `/orgs` | 创建账套 |
| 2 | W1 | GET  | `/orgs` | 列出账套 |
| 3 | W1 | POST | `/orgs/{id}/imports` | 上传+解析余额表 |
| 4 | W1 | GET  | `/orgs/{id}/imports` | 列出导入 |
| 5 | W1 | GET  | `/orgs/{id}/imports/{iid}/rows` | 分页读余额行 |
| 6 | W2 S4 | POST | `/orgs/{id}/reports/{kind}/generate` | 生成 BS / PL |
| 7 | W2 S4 | GET  | `/orgs/{id}/reports` | 列出已生成报表 |
| 8 | W2 S4 | GET  | `/orgs/{id}/reports/{rid}` | 报表详情 + cells |
| 9 | W2 S4 | GET  | `/orgs/{id}/reports/{rid}/export?format=xlsx` | 导出 Excel |
| 10 | W2 S5 | POST | `/orgs/{id}/vat-declarations` | 上传增值税申报表 |
| 11 | W2 S5 | GET  | `/orgs/{id}/vat-declarations` | 列出申报表 |
| 12 | W2 S6 | POST | `/audit-templates` | 上传审计底稿模板 |
| 13 | W2 S6 | GET  | `/audit-templates` | 列出模板 |
| 14 | W2 S6 | POST | `/orgs/{id}/audit-templates/{tid}/render` | 用报表数据渲染模板 |

外加 `/health` 健康检查（W1 起；Stage 1 增加 encryption block）。

---

## 5. DB Schema 演进 (v1 → v4)

| 版本 | 阶段 | 新增 |
|:-:|:-:|---|
| v1 | W1 | `organizations`, `accounting_periods`, `accounts`, `trial_balance_imports`, `trial_balance_rows`, `key_meta` (Stage 1 W1+W2 合并 commit) |
| v2 | W2 S4 | `reports`, `report_cells` |
| v3 | W2 S5 | `vat_declarations` |
| v4 | W2 S6 | `audit_templates` |

迁移机制（`schema.py.MIGRATION_STEPS` + `db.run_migrations`）幂等：每个
step 的 DDL 都用 `CREATE TABLE IF NOT EXISTS`，旧库重启会按需补建新表，
不重写已有表的内容。

---

## 6. 端到端验收脚本最终结果

`d:\OpenAkita\.venv\Scripts\python.exe plugins/finance-auto/scripts/m1_w2_acceptance.py`：

```
=== Step 1: Create org ===
  org_id=org_6a15ac992bda

=== Step 2: Upload balance table ===
  built synthetic sample: ...\balance.xlsx
  http=201 rows=8

=== Step 3: Generate balance sheet (W2) ===
  report_id=rep_58148775a04c cells=51
  BS_1001 (货币资金) = 205000.0

=== Step 4: Export report to .xlsx + re-open ===
  sheet=balance_sheet rows=53 bytes=7312
  first body row: ('流动资产', 'BS_SECTION_CURRENT_ASSETS', 0)

=== Step 5: Upload VAT declaration ===
  output=1500000.0 input=900000.0 payable=600000.0

=== Step 6: Upload audit template + render ===
  tpl_id=tpl_4e1e0e1c8fcb placeholders=5 unknown=0
  rendered A1='测试公司 (W2 验收) - 2025 资产负债表抽样底稿' B3=205000

=== Step 7: Inspect raw SQLite for ciphertext + W2 rows ===
  key_meta.enabled=1 seed=env
  org.name on disk = ''
  trial_balance_rows: total=8 encrypted=8 ratio=100.00%
  reports=1 vat=1 audit_templates=1

Summary written to D:\OpenAkita\_m1_w2_acceptance_result.json
```

退出码 **0**。每一步的关键指标：

* HTTP：1, 2, 3, 5, 6 上传/生成均 201；4, 6 导出 200。
* `BS_TOTAL_ASSETS`、`BS_TOTAL_LIAB`、`BS_TOTAL_EQUITY` 三个合计行均
  > 0，且 `BS_TOTAL_LE` 与 `BS_TOTAL_ASSETS` 差值在 0.01 容差内（公式
  正确）。
* 加密验证：`organizations.name` 在磁盘上为空字符串（哨兵），
  `trial_balance_rows[*]._encrypted_payload` 8/8 非空（每行 60-269
  字节密文），与 Stage 1 的 W1 重放结果一致。
* 审计渲染：A1 标题 Jinja 替换正确，B3 数字单元格被 float 强转
  205000，保留数字格式；模板的 `{{ BS_1122 }}` 短语法和
  `{{ cells.BS_1001.value }}` 长语法两条路径都通了。

---

## 7. 实际用时 / 资源消耗

* 实际开发用时：约 1.5 小时（**含**重读设计文档 + 8 次 commit + 一次端
  到端跑通）。
* pytest 整套耗时：~3.9 s（55 cases）。
* benchmark 跑 3+1 次共耗时：约 35 s（含 Excel COM 启动 ~10 s）。
* W2 端到端验收脚本：约 3.5 s（synthetic 余额，无 COM）。

---

## 8. 设计差距 / 未实施项（建议 W3 接手）

下面这些条目都是**设计文档已经提到、本周有意识地推迟**的，不是 bug。

| ID | 条目 | 原因 | 触发条件 |
|---|---|---|---|
| W3-1 | **跨期公式 `REPORT_PREV()`** 未实现 | 需要先有"账期 DAG"，依赖 W3 manual_inputs schema | M2 起所有跨期校验都要用 |
| W3-2 | **`audit_workpaper` 行业覆盖 / industry_overrides** | 二维 (准则 × 行业) 的 YAML 加载器还只做了 `extends` 一维 | 当业务方提交首份行业覆盖文件 |
| W3-3 | **xltpl 模板 .xlsx 文件**（4 份 YAML 引用的 `xltpl_file`） | 当前导出走 openpyxl programmatic，质量满足 W2 验收；xltpl 模板由设计师手刷 | 当美工组交付 |
| W3-4 | **省份特异 VAT dialect** | 各省 .xlsx 行号差几行，需要真实样本 | 收到第一份 BJ / GD / SC 实际文件 |
| W3-5 | **附加税费明细子表 parser** | W2 仅抽取 `surtax_total` 合计 | 当业务方需要分项追溯 |
| W3-6 | **审计模板版本化 / 多组织 ACL** | 当前 `audit_templates` 表全局共享、re-upload 直接写新行 | M2 多用户上线 |
| W3-7 | **KeyManagerRegistry（每账套独立密钥）** | v0.3 §5.1 LRU=5，本周仍单一 key_meta | M2 引入多租户隔离 |
| W3-8 | **annual key rotation script** | v0.3 §2.5 | 第一个年度切换 |
| W3-9 | **一年期 trial_balance_rows write_only 流式** | 现 openpyxl 全量序列化，1500 行 ~2.7 s | 出现 > 5000 行单家公司明细 |
| W3-10 | **win32com .xls→.xlsx 应急 fallback** | benchmark 验证 COM 在 1500 行场景下 5.8x 慢 + 不稳定，仅留作 fallback | xlrd / pyexcel 都解不开的合法 .xls |

> 完整设计文档相对应章节：v0.3 INDEX §6.x；v0.3 Part Infra §1, §2, §5；
> v0.3 Part Biz §3.4, §4。

**未触发新的「阻塞性问题」**。所有 8 个 stage 按计划完成，没有动设计
没说的功能，也没有动 OpenAkita host 内核（`src/openakita/` 仍是 W1 状态
未改）。

### 7.1 已知小瑕疵 / 自我修复记录

| 现象 | 修复 |
|---|---|
| `keyring.__version__` 不可靠 | 改用 `importlib.metadata.version('keyring')` |
| `IntegrityError: NOT NULL` 在 organizations.name 加密后 | `""` 哨兵 + 模型 `from_attributes`（覆盖 `Literal` 校验） |
| `aiosqlite.Row` `in dict.keys()` 行为不一致 | `_has_blob` helper + `noqa: SIM118` |
| `ruff UP017 datetime.UTC` | 保持 `timezone.utc` 与 W1 风格一致 |
| `ruff N999 finance-auto` | 工程级别遗留，未单独处理（W1 之前就如此） |
| Excel COM 重复启动 0xC0000005 | benchmark 强制 COM 路径只跑 1 run |
| openpyxl 模板 `__SUM__` 行被数据行覆盖 | snapshot+truncate+re-emit 策略 |
| pytest async fixture 找不到 `service.startup` | 改用 `db.init()`（W1 真实接口） |
| 测试文件被 `.gitignore` 排除 | 加 `!plugins/**/test_report_*.py` 白名单 |

---

## 9. M1 W3 启动建议（按 v0.3 INDEX §6 W3 章节）

> W3 主题：Beancount 桥接 + manual_inputs 跨期 + 重分类 + UI 第一刀。

### 9.1 核心任务（按依赖顺序）

1. **manual_inputs schema + API**
   - 4 张子表（处置子公司、对外投资、其他流量、跨期调整）
   - schema v5 migration
   - Pydantic 模型 + 简单上传 / 列出 / 编辑端点
   - **前置**：无；**可并行**：与 W3-2 同时开

2. **Beancount 双写桥**（v0.3 Part Biz §5）
   - 把 `trial_balance_rows` 投影成 Beancount 文本
   - 仅作为只读"参考布局"先生成 `.beancount` 文件
   - **前置**：W2 已完成的 `trial_balance_rows` 解码层
   - **可并行**：与 manual_inputs 同时开

3. **跨期 `REPORT_PREV()` 公式**
   - 让 `PL_RETAIN_BEGIN` 真正能跨期取数
   - **前置**：W3-1（manual_inputs），可与 W3-2 并行

4. **重分类规则**（v0.1 §5.2 / §5.3）
   - 应收账款贷方 → 预收
   - 预付账款贷方 → 应付
   - 其他应收款贷方 → 其他应付
   - **前置**：W2 报表生成器（已完成）
   - **可并行**：与 W3-1, W3-3 同时开

5. **行业 overrides 加载器**（v0.3 §3.6）
   - YAML extends 已有；加 `industry_overrides/<industry>.yaml`
   - **前置**：无

6. **首版 React 前端 BS 页面**
   - 上传余额表表单 + 列出报表 + 显示 BS 表格 + 单元格点击展示追溯链
   - **前置**：W1 + W2 后端（已完成）
   - **可并行**：与 W3-1..W3-5 完全独立

### 9.2 W3 启动前需要用户决策的事

**无**。设计文档 v0.3 INDEX §6 + Part Biz §3 已经给到 W3 的所有契约。

如果业务方在 W3 启动前回信确认了 `BS_GE_1606_ROU` / `BS_GE_2241_CL` /
`BS_GE_2811_LL` 这 3 行的实际编码，可以把 YAML 里的 `code: "TBD"` 改成
正确编码并 commit 一个 `fix(finance-auto): lock TBD account codes per
business confirmation`。这是非阻塞的：W3 也能在 TBD 状态下推进。

### 9.3 是否可继续自动推进 W3？

**可以**。W2 验收脚本已经验证后端可用，加密、报表、申报、审计模板
四条线全部通过 HTTP 路径跑通。建议下一轮自动推进时直接进 W3，按
9.1 的 6 个任务并行 / 串行编排。

---

## 10. 附：本周关键文件 grep 索引

| 关键词 | 落地文件 |
|---|---|
| AES-256-GCM | `finance_auto_backend/key_manager.py` |
| `_encrypted_payload` | `finance_auto_backend/encryption.py`, `routes.py` |
| YAML extends | `finance_auto_backend/config/yaml_loader.py` |
| AST 沙箱 | `finance_auto_backend/report_generator.py` |
| Jinja2 渲染 | `finance_auto_backend/services/audit_template.py` |
| Golden Tax IV | `finance_auto_backend/parsers/vat_declaration.py` |
| Renderer factory | `finance_auto_backend/renderers/factory.py` |
| migrate-encrypt CLI | `scripts/migrate_encrypt.py` |
| W2 acceptance | `scripts/m1_w2_acceptance.py` |

---

*— 报告结束 — 文件大小 ~16 KB，符合 ≤ 25 KB / 500 行的验收要求*
