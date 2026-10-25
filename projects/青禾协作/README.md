# 青禾协作 · 根据聊天记录更新任务表

本地网页工具（单机、单人、不上线）：上传「任务表 CSV + 聊天记录 CSV」→ 真实调用外部对话模型产出字段级建议 → 逐条核对并确认 → 只有确认的写回 → 导出三份产物（任务表.csv / 建议清单.json / 变更说明.md）；同一批重复导入不新增、不覆盖。

## 目录

- `backend/`：FastAPI 后端（业务、模型调用、CSV、持久化、测试）
- `frontend/`：Vite + TypeScript 纵向切片界面（保留到正式产品）
- `scripts/restart-check.sh`：重启恢复检查钩子（`verify.sh` 调用）
- `data/`：运行时产物（state.json、exports/、logs/），已 gitignore
- `docs/`：PRD、阶段文档、证据包、项目状态

## 环境要求

- Python 3.12（`python3.12` 可用）
- Node.js 20+（前端构建用）
- DeepSeek API Key（验收前提供即可；开发期用 mock 测试推进，不阻塞）

## 启动

```sh
# 后端（会自动建 .venv、装依赖、起服务；首次会生成 .env 提示填 Key）
cd backend
./run.sh
# 打开 http://127.0.0.1:8000
```

```sh
# 前端（修改界面时用；Vite dev 带 /api 代理到 8000）
cd frontend
npm install
npm run dev        # http://localhost:5173
npm run build      # 构建产物 frontend/dist，由后端挂在 8000 端口
```

后端 `.env`（复制 `.env.example` 填写，勿提交）：
- `ANTHROPIC_API_KEY`：DeepSeek 密钥
- `MODEL_ID`：默认 `deepseek-chat`（可切 `deepseek-v4-pro`）
- `ANTHROPIC_BASE_URL`：默认 `https://api.deepseek.com/anthropic`
- `MAX_OUTPUT_TOKENS` / `MODEL_TIMEOUT_SECONDS`

## 验证

```sh
# 后端 mock 测试（不调真实模型，20 项）
cd backend
.venv/bin/python -m pytest -q

# 前端类型检查 / lint / 构建
cd frontend
npm run build && npm run lint

# 重启恢复检查（起服务→写入→杀进程→再起→读回）
cd ..
bash scripts/restart-check.sh

# 阶段自检（在工具包根目录）
./verify.sh 青禾协作 阶段2-1
```

## 使用流程

1. 打开 http://127.0.0.1:8000
2. 选择「任务表 CSV」与「聊天记录 CSV」，点「载入」
3. 点「发起分析」（真实调用模型，最多约 3 分钟）
4. 建议按任务分组、按紧急程度排序展示；每条带「性质 / 紧急 / 决定」三个标签（颜色+图标+文字）
5. 逐条「采纳 / 否决 / 修改后采纳」——都会弹二次确认（此操作不可撤销）；否决可填理由；任务表行可勾「已核对」（仅自己标记，不入导出）
6. 点「写回」（只写已采纳 / 修改后采纳的字段）
7. 点「导出三份产物」，下载三份文件
8. 用导出的「任务表.csv」+ 下一批聊天记录，回到第 2 步继续

## 测试数据

`个人资料/测试题A/`：`作业附件-初始工作清单.csv`、`作业附件-A批业务记录.csv`、`作业附件-B批业务记录.csv`。
