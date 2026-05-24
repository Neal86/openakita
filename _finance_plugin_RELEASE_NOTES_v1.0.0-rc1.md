# OpenAkita 财务自动化插件 v1.0.0-rc1 发布说明

> **状态**：Release Candidate 1
> **日期**：2026-05-24
> **License**：AGPL-3.0-only

---

## §1 一句话

**finance-auto v1.0.0-rc1** 是 OpenAkita 平台的小企业 + 一般纳税人
+ 多审计师协作财务自动化插件首个候选发布，把试算余额表 → 法定报表
+ 审计模板渲染 + 多人复核 + AI 协作 + 加密备份打包进同一个
OpenAkita 桌面/服务实例，离线即可用。

---

## §2 What's New

1. **自动从余额表生成 4 大法定报表**：资产负债 / 利润 / 现金流量
   （直接+间接）/ 所有者权益变动，按小企业准则或企业会计准则。
2. **审计报告自动生成**：上传 .xlsx 审计模板 → 填充实际值 + 智能
   简化模式（Top-N + 其他）→ 输出可交付件。
3. **多审计师协作**：项目经理 → 复核员 → 合伙人三级 RBAC，
   复核留痕 / 评论 / 签字 / 退回全部可溯源；10 个写模块均有
   应用层权限校验。
4. **合并报表**：母 + 多子公司 group，自动识别内部往来 / 销售 /
   投资抵消分录 + 自动计算少数股东权益。
5. **报表附注自动生成**：8 节 A-share 通用附注 + 数据驱动 / 叙述
   / 混合三种填充。
6. **同业对比分析**：12 行业基准（3 × 4 指标）+ AI 辅助点评。
7. **AI 辅助 9 个场景**：6 个 🟢/🟡 聚合敏感度 + 3 个 🔴 原始
   数据；全部带用户授权弹窗 + 审计日志 + WS 实时推送。
8. **重分类规则引擎**：YAML/JSON 规则 + 预览 / 应用 / **撤销**
   （新 undo API，inverse-delta 历史可回滚）。
9. **加密备份 + 恢复**：AES-256-GCM + PBKDF2-HMAC-SHA256
   **600 000 迭代**（OWASP 2023）+ 路径遍历沙盒。
10. **Tauri 桌面原生**：consent / system-info / notification /
    save-path 4 个 Rust 命令端到端打通。
11. **新增端点 + URL 前缀**：`DELETE /orgs/{id}` （cascade 可选）
    + 全部路由迁移到 `/v1/`（老路径 308 redirect 向后兼容）。

---

## §3 系统要求

| 项 | 最低 | 推荐 |
| --- | --- | --- |
| Python | 3.11 | 3.12 |
| 操作系统 | Windows 10 / macOS 12 / Linux glibc 2.28+ | Windows 11 / macOS 14 / Ubuntu 22.04 |
| 内存 | 2 GB | 4 GB+ |
| 磁盘 | 500 MB | 5 GB+ |
| 网络 | 离线可用，AI 按需联网 | 同左 |

---

## §4 安装

```powershell
git clone https://github.com/openakita/openakita.git
cd openakita
python -m venv .venv ; .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pip install -r plugins/finance-auto/requirements.txt   # 6 个核心包
openakita serve   # 插件自动加载 + schema 自动迁移到 v14
```

Headless / Docker：**必须** 设 `OPENAKITA_FINANCE_AUTO_PASSPHRASE`
（32+ 字节高熵）。完整指南：`plugins/finance-auto/docs/DEPLOY_DOCKER.md`。

首次配置 LLM：编辑 `plugins/finance-auto/config/ai_endpoints.yaml`
（Ollama 推荐 `ollama pull llama3:8b`）。

---

## §5 快速验证

```powershell
# 10/10 acceptance（~25 秒）
.venv\Scripts\python.exe plugins/finance-auto/scripts/run_all_acceptance.py
# 期望：Total: 10/10 passed

# 或 pytest（280 用例 ~50 秒）
.venv\Scripts\python.exe -m pytest plugins/finance-auto/tests/ -q
# 期望：280 passed

# API 健康
curl http://127.0.0.1:18900/api/plugins/finance-auto/v1/health
```

---

## §6 Known Limitations

诚实清单（v1.0.0-rc1，详 `CHANGELOG.md`）：

1. **AI 🔴 raw 场景 CI 中走 mock**：S6/S7/S11 通过 monkey-patch
   注入 stub local endpoint；生产需配置真实 Ollama / OpenAI-
   compatible。
2. **Tauri 命令未进端到端 IPC harness**：单元覆盖已有，live shell
   端到端测试在 v1.0 GA 路线。
3. **附注模板 8 节**：A-share 实际常含 ~40 节；v1.x 扩展。
4. **同业基准是 JSON 静态数据**：12 行业 × 4 指标；v1.x 计划接入
   CSRC / Wind。
5. **WebSocket server-side replay**：客户端 cursor + `?since=`
   已就位，服务端 replay buffer 在 v1.x。
6. **多用户密钥协商**：组件密钥按 `key_meta` 全局共享，per-user
   sub-key 在 v1.1。
7. **Docker 镜像未本机 build 验证**：compose / k8s 模板已就位，
   官方 image push 在 v1.0 GA。
8. **多机部署**：当前 SQLite + WAL 仅支持单机；Postgres backend
   + 远程 keyring 在 v1.1。
9. **`m2_closing_acceptance.py` 偶发 TIMEOUT**：单独 subprocess
   始终 3.1s natural exit；批量第 N 次偶发 120s timeout，疑似
   scheduler 非 daemon + WAL 状态污染。v1.0 GA 修。

> `DELETE /orgs/{id}` 和 `/v1/` URL 前缀两条**已在 v1.0.0-rc1
> 加入**，从历史 Known Limitations 移除。

---

## §7 升级路径（v0.x → v1.0.0-rc1）

1. **备份**：复制 `data/plugin_data/finance-auto/finance.sqlite`。
2. **更新代码 + 依赖**：`pip install -r plugins/finance-auto/
   requirements.txt`。
3. **启动**：插件自动从旧 schema 迁到 v14（idempotent，含 v8 AI /
   v9 collab/consol/reclass / v10 notes-peer / v11 key-rotation /
   v12 RBAC / v13 reclass undo / v14 org.delete perm）。
4. **API 路径（可选优化）**：老路径仍 308 跳转，新代码切到
   `/api/plugins/finance-auto/v1/<endpoint>` 省一次往返。
5. **旧 200k PBKDF2 备份**：自动 `kdf_iterations` 兼容，无需操作。

---

## §8 反馈渠道

* **GitHub Issues**：OpenAkita 仓库 `area:finance-auto` 标签。
* **审查报告**：`_finance_plugin_audit_report{,_round2,_round3}.md`
  三轮独立复审全量记录 + `_finance_plugin_audit_extended_report.md`
  扩展审查。
* **变更日志**：`plugins/finance-auto/CHANGELOG.md` keep-a-changelog
  格式。

---

## §9 致谢

基于 **OpenAkita 核心** (AGPL-3.0-only) +
**FastAPI / aiosqlite / Pydantic** Python 异步底座 +
**openpyxl / xlrd 1.2.0 / xltpl** Excel 三件套 + **cryptography**
AES-GCM + **keyring** 跨平台密钥环 + **React 18 / Tauri 2.x** 桌面
栈。KDF 参数取自 OWASP 2023 password storage cheat sheet。

完整 commit 列表见 `git log --oneline plugins/finance-auto/`。

---

## §10 发布命令（不打 tag，等你拍板）

```powershell
git log -1 --format='%h %s'                  # 确认 RC1 收尾 commit
# 你确认后再执行：
# git tag v1.0.0-rc1 <HEAD>
# git push origin v1.0.0-rc1
```

PyPI / GitHub Release push 在 v1.0 GA 随主体统一发布。
