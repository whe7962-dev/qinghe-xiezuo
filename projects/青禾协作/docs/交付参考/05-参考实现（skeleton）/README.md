# skeleton —— 青禾协作 · 根据聊天记录更新任务表

本地网页：上传任务表 + 聊天记录 → 真实调用模型分析 → 逐条核对建议 → 确认后写回 → 导出。

本骨架按 `../方案.md` 与 `../PRD.md` 生成，可独立运行。

## 运行（一条命令）

```sh
cd skeleton
./run.sh            # 自动建 .venv、装依赖、起服务
# 或手动：
#   python3.12 -m venv .venv
#   .venv/bin/pip install -r requirements.txt
#   cp .env.example .env   # 填入模型密钥
#   .venv/bin/uvicorn app.main:app --reload
# 打开 http://127.0.0.1:8000
```

模型服务由 `.env` 注入（服务地址 / 模型名 / 密钥），页面不展示密钥。本项目选定 **DeepSeek V4 Pro**（思考型模型）。

## 测试

```sh
.venv/bin/python -m pytest -q
```

## 流程

载入 → 分析 → 核对 → 确认 → 写回 → 导出 → 载入下一批 → 重复导入（幂等）。

- 每条建议：任务编号（对不上标「不对应现有任务」）、字段、原值、建议值或「不建议修改」、依据聊天编号与原话、不确定点。
- 决定四种：待确认 / 采纳 / 否决 / 修改后采纳；只有采纳与修改后采纳写回对应字段。
- 同一批相同编号、相同正文再次导入：不新增行动、不覆盖已确认字段。
- 导出三样：`exports/任务表.csv`（可再次载入）、`exports/建议清单.json`、`exports/变更说明.md`。
- 指标端点：`GET /api/metrics`（模型失败率、建议可核对率、重复导入幂等率、已确认字段保护率、产物齐全率）。

## Harness 组件落地（对应 ../方案.md Step 3）

| 组件 | 落点 |
|---|---|
| s01 Agent Loop | `llm_client.py`：重试、超时、token 上限、stop_reason 完整处理、思考块跳过 |
| s02 工具系统 | `tools.py`：六个工具的 JSON schema、参数校验、统一 ToolResult 错误回传 |
| s03 权限系统 | `permission.py` + `harness.py` 的 pre 钩子：未经采纳不写回、越出 exports/ 拒绝 |
| s04 钩子系统 | `hooks.py`：PreToolUse 可阻断、PostToolUse 可观察、异常不影响主循环 |
| s05 任务规划 | `planner.py`：阶段状态机 + 持久化 + 进度可查询 |
| s15 集成 Harness | `harness.py`：单一循环串起 store / tools / hooks / metrics / planner |
| 可观测 / 可度量 | `observability.py`：结构化日志、指标、轨迹 |

## ⚠️ 按默认假设实现的地方（PRD 第 6.2 节）

| 假设 | 取值 |
|---|---|
| 编程语言/框架 | Python + FastAPI + 原生网页 |
| 模型 | 配置注入，本项目选定 DeepSeek V4 Pro（可切 deepseek-chat 提速，或 glm 等） |
| 分析方式 | 同步 + 前端「处理中」状态（s11 后台任务未启用）；思考型模型单批约 1–2 分钟 |
| 数据访问边界 | 只读写项目内 `exports/`、`state.json`、`logs/` |
| 导出格式 | 任务表 CSV（UTF-8 带 BOM）+ 建议清单 JSON + 变更说明 Markdown |
| 状态载体 | 服务内存 + `state.json` / `state/plan.json` 持久化，跨批次连续 |
| 组件 | s01/s02/s03/s04/s05/s15 启用；s06/s08/s09/s10/s11 第一版不启用 |

## 目录

```
app/
  main.py          FastAPI 入口与路由
  harness.py       集成 Harness（单一循环）
  config.py        .env 配置注入
  models.py        任务表 / 聊天 / 建议 / 决定
  csv_io.py        CSV 读写（UTF-8 BOM）
  tools.py         工具系统（schema + 校验 + 统一错误）
  rules.py         业务规则（十条规则落地）
  permission.py    写回门槛（s03）
  hooks.py         钩子系统与变更说明（s04）
  planner.py       流程阶段跟踪（s05）
  observability.py 日志 / 指标 / 轨迹
  prompt.py        系统提示词
  llm_client.py    模型调用（重试 / 超时 / 思考块）
  analyzer.py      分析：任务表 + 聊天 → 建议
  store.py         会话状态
web/               前端页面
tests/             单元与集成测试（FakeLLMClient，不调真实模型）
run.sh             一条命令启动
```

## 说明

- 分析必须真实调用模型：`analyzer.py` 只把业务规则写进提示词，不预写任何附件的处理结论。
- 模型调用失败 → 页面进入失败状态，已确认的任务表与决定保留，配置恢复后可重试。
- 程序不代替使用者确认；未经采纳不写回。
