# COC 智能体跑团辅助系统(当前未完工)

局域网联机 CoC（克苏鲁的呼唤·七版）跑团 Web 应用：1 名 KP + 2~4 名玩家在浏览器里即开即玩。
能力：七版规则建卡与检定、房间实时联机（WS + 心跳重连 + 存档续玩）、双聊天框（剧情 / 闲聊分离）、
**双模式主持**（AI 全自动 / AI 协助真人 KP）、模组解析（上传 → 结构化 → 挂载驱动剧情）。

- 总控/任务清单：`goal.md`（按 checkbox 推进，阶段 0~5 已完成，阶段 6 打磨与演示进行中）
- **一键启动**：双击根目录 `start.bat`（单端口 8000 托管前后端，见 `docs/部署文档.md`）
- 规则笔记：`docs/coc7-rules.md`；项目简介：`docs/项目描述.md`
- 文档：**`docs/部署文档.md`**（10 分钟跑起来 / 局域网开团 / FAQ）、**`docs/使用说明.md`**（KP 与玩家操作）
- 前端 Vue3 + Vite + TS + Pinia + Element Plus；后端 FastAPI + SQLModel(SQLite)；LLM 走 OpenAI 兼容协议（GLM / DeepSeek / 千问 / OpenAI 可切换，无 key 可降级纯人工或 Mock 演示）

## 目录结构

```
.
├── goal.md               # 项目总控文档
├── docs/                 # 规则笔记、项目简介
└── project/
    ├── frontend/         # Vue3 前端（npm）
    └── backend/          # FastAPI 后端（.venv + pip）
        ├── app/          # main.py / api / ws / rules(规则引擎) / llm / agent(提示词与记忆) / models / seed
        ├── scripts/      # init_db / migrate_44 / parse_seed_data 等
        └── tests/        # pytest
```

## 环境要求

- Node.js ≥ 22（前端 `package.json` engines 要求 `^22.18.0 || >=24.12.0`）
- Python ≥ 3.11

## 一键启动（推荐，单端口）

Windows 下双击根目录 **`start.bat`**：自动检测 Python/Node → 建 `.venv` 装依赖 → 补 `.env`
→ 建库或补增量迁移 → 构建前端 → 起后端（**前端产物由后端单端口托管**，只用 8000 一个端口）
→ 打印局域网地址并打开浏览器。参数：`start.bat 8080` / `--rebuild` / `--check`。

细节、局域网开团与排错见 **`docs/部署文档.md`**。

## 本地启动（开发模式，前后端两个终端）

> 开发时前端走 Vite（5173）并用代理转发 `/api` 与 `/ws` 到后端，改代码热更新最快。
> 非开发场景请用上面的一键启动（单端口）。

### 1) 后端（端口 8000）

```bash
cd project/backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac/Linux:
# source .venv/bin/activate

pip install -r requirements.txt

# 生成本地配置（密钥只进本地，绝不提交）
# Windows:
copy .env.example .env
# Mac/Linux:
# cp .env.example .env

# 首次建库 + 灌入职业/技能种子数据（数据存 backend/data/，不入库）
python -X utf8 scripts/init_db.py

# 启动
python -X utf8 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端 API 文档：http://127.0.0.1:8000/docs

### 2) 前端（端口 5173）

```bash
cd project/frontend
npm install
npm run dev
```

浏览器打开 http://localhost:5173 即可（已配 Vite 代理到后端）。

### 3) 可选：LLM 配置

不配置 key 也能跑：无 key 自动回退纯人工主持；`LLM_MODEL=mock` 启用演示模式（不发真实请求）。
配置真实 LLM 时填 `backend/.env` 的 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`（建议模板见 `.env.example`），
或运行后在 KP 控制台「LLM 设置」面板在线配置（4.4 起存 `llm_config` 表，`llm_config` 为权威、`.env` 仅作首次 seed）。
可选：`backend/data/scenario_brief.txt`（可由 `scenario_brief.example.txt` 复制而来）提供示例模组剧情骨架。

## 测试

```bash
# 后端（backend 目录下）
python -X utf8 -m pytest

# 前端单元测试
cd project/frontend && npm run test:unit
```

## 团队协作约定

- 本仓库 **private**，以 `main` 为主干。新成员拉取 → 开 `feature/xxx` 分支 → 完成开发推分支 → 提 Pull Request 由他人 review 后合入。
- **密钥与数据不入库**：`.env`、`*.db`、`backend/data/` 均已被 `.gitignore` 拦截。新成员首次 clone 后需自行 `copy .env.example .env` 并 `scripts/init_db.py`。
- 需要人工提供的资料（规则书 PDF、手抄表、模组 PDF、参考 skill）不进本仓库，另在 COC_project 归档目录管理。
- 数据库结构变更时（`goal.md` §11 有记录）用 `python -X utf8 scripts/init_db.py --force` 删库重建，或在已有库上跑 `scripts/migrate_44.py`（按需）。
- 重要变更与决策更新 `goal.md` §11 变更记录。
