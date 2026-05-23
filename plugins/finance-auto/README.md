# finance-auto (M1 W1 skeleton)

OpenAkita 财务自动化插件 — M1 W1 完成 **创建账套 → 上传余额表 → 解析入库 → 查询** 的最小端到端闭环。

## 当前能力

- 创建账套 (`POST /orgs`) / 列出账套 (`GET /orgs`)
- 上传余额表 (`POST /orgs/{org_id}/imports`) — 自动用 openpyxl / xlrd / pywin32+COM 三段降级解析
- 列出导入记录 / 分页查询解析结果
- 科目编码归一化（4 位一级 + 明细 child）
- SQLite WAL 模式默认启用，敏感表保留 `_encrypted_payload` 列等待 M1 W2 接入 KeyManager

## 目录

```
plugin.json                          ← 插件清单（routes.register / data.own）
plugin.py                            ← OpenAkita Plugin 入口（on_load/on_unload）
finance_auto_backend/
    db.py                            ← aiosqlite 连接封装 + WAL PRAGMA
    schema.py                        ← 5 张表 DDL（含 _encrypted_payload 占位）
    models.py                        ← 5 个 Pydantic 模型 + 响应包络
    routes.py                        ← FastAPI 路由 + Service 层
    key_manager.py                   ← M1 W2 KeyManager 桩（is_enabled() == False）
    parsers/xls_parser.py            ← 三段降级 .xls/.xlsx 解析器
    normalizers/account_code.py      ← 科目编码归一化
_e2e_run.py                          ← 不需要启动 OpenAkita 就能验证的端到端 harness
README.md                            ← 本文件
```

## 启动端到端验证

```powershell
d:\OpenAkita\.venv\Scripts\python.exe plugins\finance-auto\_e2e_run.py `
    --port 18901 --db tmp_finance_auto_e2e.sqlite --reset
```

服务起来后用 curl 或 PowerShell 的 `Invoke-RestMethod` 跑设计文档里的 5 步 demo（详见 `_m1_w1_completion_report.md` §5）。

## 接入 OpenAkita 后端

插件遵循 OpenAkita 标准 Plugin 协议（`PluginBase` + `on_load(api)`），将本目录复制到 `data/plugins/finance-auto/` 后重启即可被 PluginManager 自动加载。路由会以 `/api/plugins/finance-auto/...` 前缀出现在 FastAPI app 上。
