# COC 智能体跑团辅助系统 — 项目总控文档（goal.md）

> 本文档是项目的总控文件：记录目标、技术栈、架构、分阶段任务清单与验收标准。
> 每完成一项就把 `[ ]` 改为 `[x]`，按顺序从上往下推进。

---

## 0. 当前状态

- [x] 项目规划完成（本文档）
- [x] Agent 配置设计完成（§6，借鉴 model_skills 经验）
- [x] 阶段 0：工程初始化
- [x] 阶段 1：数据模型与 API 契约
- [x] 阶段 2：角色卡模块（规则引擎 + 建卡向导，浏览器实测通过）
- [x] 阶段 2.5：建卡体验完善（推迟项清单，见 §7）
- [x] 阶段 3：局域网真人团（★ MVP 核心：房间 / WS / 双聊天框 / KP 控制台 / 存档）——3.1~3.4 完成
- [x] 阶段 4：LLM 集成、Agent 配置与双模式主持（已拆分 4.1~4.4，见 §7，2026-09-06）——4.1 + 4.1+ 修订 + 4.2 + 4.3 + 4.4 完成（2026-09-08，阶段 4 全部完成）
- [x] 阶段 5：模组解析（上传 TXT/PDF/DOCX → 手动选模型解析 → 模组库校对 → 房间挂载，2026-09-10）
- [ ] 阶段 6：打磨与演示（2026-09-10 重写为 6 块，含 UI 美化 / 单端口部署 / 安全收口，见 §7）——6.1 已完成（2026-09-11）

**MVP 定义**：局域网内 1 个 KP + 2~4 个玩家，用浏览器开一局真人 CoC 团（建房 → 加入 → 双聊天框 → 掷骰 → KP 改状态 → 存档续玩）。
**下一步动作**：阶段 6.2 UI 重构美化（9 小项，先做 ①设计令牌 + Element Plus 暗色地基；详见 §7 6.2）。
阶段 6.1 已于 2026-09-11 完成（单端口托管 / start.bat 一键启动 / .env.example 与首次配置引导 / 部署文档 + 使用说明，详见 §11）。
阶段 5 已于 2026-09-10 完成（模组库 + 结构化解析 + 房间挂载）；同日按用户 7 条实测反馈做了第二批修复（检卡 / 检定下放任意技能 / 技能上限 / 按房间 token / 模组库返回 / 大厅 API 配置 / 解析检测门禁，详见 §11）。

---

## 1. 项目一句话目标

构建一个**局域网联机的 Web 应用**：玩家和守秘人（KP）在同一局域网内用浏览器组队跑 CoC 团，系统提供**角色卡管理、房间联机、双聊天框（玩家聊天 / 剧情聊天分离）、双模式主持（AI 全自动主持 / AI 辅助人类主持）、本地存档、模组解析**能力。定位为高校赛设计作品。

**明确不做**（范围边界，防需求漂移）：
- 移动端原生 App（只做 Web，浏览器自适应即可）
- 云端账户系统（无注册登录，无跨公网服务）
- 任何付费/商业化功能

---

## 2. 现有资料盘点（other/ 文件夹的用途）

| 文件 | 用途 | 使用时机 |
| --- | --- | --- |
| `智能体跑团辅助系统项目计划书.docx/pdf` | 需求来源：功能模块、范围界定、风险对策 | 需求基线，本文档已提炼 |
| `coc七版规则空白卡.xlsx` | 数据模型参考：8 大属性、衍生值、160+ 职业、技能表、武器/防具/载具、理智规则、背景故事字段 | 阶段 1 设计数据库 schema 与角色卡 JSON 结构时对照 |
| `克苏鲁的呼唤第七版守秘人规则书 Version2002.pdf` | 规则来源：检定规则、理智规则、疯狂表、对抗检定等 | 阶段 2 实现规则引擎时查证公式；阶段 5 做规则库时抽取关键章节 |
| `logo.png` | 品牌素材 | 前端界面标题栏/登录页 |
| `model_skills/`（4 个开源跑团 skill） | Agent 设计经验来源：KP 风格系统、叙事输出协议、剧情记忆、防超游信息隔离、线索生命周期、模组结构化 | 本文档 §6「Agent 配置设计」的主要参考 |
| `other/table/*.txt`（10 张手抄表） | 规则数值与数据源：技能/职业/DB体格/MOV/护甲/属性注释已入库使用；武器列表/物价/资产/生活水平待阶段 2.5 卡片编辑时录入 seed | 阶段 2 已用 4 张；武器/资产表待阶段 2.5 |

---

## 3. 技术栈定案（前端已按用户要求从 React 修正为 Vue3）

| 层 | 选型 | 理由 |
| --- | --- | --- |
| 前端框架 | **Vue 3 + Vite + TypeScript** | 用户指定 Vue3；Vite 开发体验好；TS 保证联机消息协议类型安全 |
| 前端状态 | Pinia | Vue3 官方推荐，房间/角色卡/聊天状态统一管理 |
| 前端 UI 库 | Element Plus | 中文生态成熟，表单/表格组件齐全，适合角色卡编辑这类重表单场景 |
| 路由 | Vue Router | 官方标准 |
| 实时通信 | 原生 WebSocket + 自定义 JSON 消息协议 | FastAPI 原生支持 WS，无需引入 socket.io，协议见 §5.3 |
| 后端框架 | **Python FastAPI** | 异步 + 原生 WebSocket + 自动 OpenAPI 文档 |
| 数据库 | **SQLite + SQLModel** | 嵌入式零部署，SQLModel 与 FastAPI/Pydantic 无缝集成 |
| LLM 接入 | OpenAI 兼容协议适配层（可配置 base_url + api_key + model） | 智谱 GLM、DeepSeek、OpenAI 均兼容 OpenAI 格式，一套代码切换供应商 |
| 局域网发现 | MVP：显示服务器 IP+端口链接/二维码；增强：UDP 广播自动发现 | 先保可用，再提升体验 |
| 部署形态 | 前端 `vite build` 产物由 FastAPI 静态托管，**单端口启动** | 局域网用户只需访问一个地址 |

---

## 4. 系统架构

```
浏览器（Vue3 SPA，多端：玩家×N + 守秘人×1）
        │  HTTP(REST)        WebSocket(实时)
        ▼
FastAPI 后端（唯一权威状态源，以主持人端裁定为准）
 ├─ 业务层：房间管理 / 角色卡 / 聊天 / 存档 / 模组解析
 ├─ 规则引擎：CoC7 检定计算（纯函数，前后端可复用的算法放后端）
 ├─ LLM 适配层：OpenAI 兼容 → GLM / DeepSeek / OpenAI（可插拔）
 │    └─ Function Calling：LLM 只能通过工具调用触发掷骰与状态变更
 └─ 数据层：SQLite（角色卡JSON / 房间 / 聊天历史 / 存档 / 模组库）
        │
        ▼
外部 LLM API（HTTPS，可离线降级为纯人工主持）
```

关键架构原则：
1. **服务端权威**：所有状态变更（骰子、属性、剧情推进）由后端裁定后广播，客户端只上报意图，防止多端写入冲突。
2. **LLM 无直接写权**：LLM 通过 function calling 请求操作（如 `roll_check(skill, difficulty)`），由规则引擎执行后返回结果，LLM 基于结果继续叙事。
3. **本地优先**：所有数据落 SQLite 文件，导出角色卡为 JSON 文件，无云依赖。

---

## 5. 数据模型草案（阶段 1 细化定稿）

### 5.1 角色卡 `investigator`（核心，JSON 存储 + 关键字段拆列）
参照 `coc七版规则空白卡.xlsx`：
- **基本信息**：姓名、性别、年龄、时代（古典/现代）、职业、居住地、出生地
- **属性（8+1）**：STR 体质 CON 敏捷 DEX 外貌 APP 意志 POW 智力 INT 教育 EDU 体型 SIZ + 幸运 LUK
  - 标准生成：STR/CON/DEX/APP/POW/LUK = 3D6×5；SIZ/INT/EDU = (2D6+6)×5
- **衍生值（规则引擎计算）**：HP=(CON+SIZ)/10 向下取整；MP=POW/5；SAN=POW；DB 伤害加值与体格（由 STR+SIZ 查表）；MOV 移动率（由 STR/DEX/SIZ 决定）
- **技能表**：`{技能名: {基础值, 增长值, 职业标记}}`（职业点 = EDU×4，兴趣点 = INT×2，按所选职业分配）
- **战斗**：武器列表（名称/技能/伤害/射程/次数/装弹）；防具
- **背景**：个人描述、思想信念、重要之人、意义非凡之地、宝贵之物、特质、伤疤恐惧
- **状态**：当前 HP/MP/SAN/幸运，理智检查标记（临时疯狂/不定疯狂），幕间成长记录

### 5.2 数据库表（SQLite）
`room`（房间：id/名称/KP/状态/创建时间）、`room_member`（成员：room_id/玩家名/角色/角色卡id/在线状态）、`message`（消息：room_id/channel[player|narrative]/sender/content/type[文本|骰子|系统]/时间）、`chat_history`（LLM 上下文：room_id/role/content/摘要标记）、`save_game`（存档：room_id/名称/剧情状态快照/时间）、`module_scenario`（模组：标题/原始文本/结构化JSON）、`llm_config`（供应商/base_url/key/model，key 仅存本地）；剧情记忆五要素表（§6.5）：`scenario_state`（场景状态）、`clue`（线索：来源/指向/验证状态/可见性）、`thread`（伏笔/未结算）、`clock`（威胁时钟）、`npc`（NPC 实体，公开身份与 KP 私有状态分离）

### 5.3 WebSocket 消息协议（初版）
统一信封：`{ type, room_id, sender, seq, payload, ts }`
- 客户端→服务端：`join_room` / `chat_send` / `roll_request` / `card_update` / `narrative_action`（玩家行动）/ `kp_decision`（KP 采纳编辑后的指令）
- 服务端→客户端：`room_state`（全量同步，重连补齐用）/ `chat_new` / `roll_result` / `card_changed` / `narrative_update` / `member_changed` / `error`
- 心跳：`ping/pong`，15s 间隔，断线自动重连后请求 `room_state` 补齐

---

## 6. Agent 配置设计（★ 游玩体验的核心）

> Agent 不只是"接一个 LLM API"。跑团体验好坏取决于：AI 会不会剧透、会不会忘记剧情、叙事是否稳定、KP 是否好控制、数值是否可信。
> 本章借鉴 `model_skills/` 四个开源 skill 的成熟经验（来源已标注），结合本项目双模式主持特点设计。**实现细节以本章为准，阶段 4 任务逐项落地。**

### 6.1 分层提示词组装（借鉴 coc-trpg-skill 的按需加载思想）

每次调用 LLM 的提示词由五层按序组装，下层不重复上层内容：

| 层 | 内容 | 大小 | 更新频率 |
| --- | --- | --- | --- |
| L1 基座层 | CoC7 KP 行为准则 + §6.3 输出协议 + 工具说明（静态、版本化） | ≈2k | 版本发布才变 |
| L2 风格层 | 当前 KP 风格参数 → 叙事指令（§6.2） | ≈0.5k | 切换风格时 |
| L3 剧情层 | 模组结构化骨架（§6.8）+ 剧情记忆快照（§6.5） | 2-3k | 场景推进时 |
| L4 状态层 | 在场调查员卡摘要（HP/SAN/关键技能/背景钩子） | 1-2k | 状态变更时 |
| L5 会话层 | 滚动对话窗口 + 旧剧情摘要 | 4-8k | 每轮 |

- 组装器是独立模块：同一份记忆与状态可服务全自动/协同两种模式，且便于离线回归测试提示词效果
- 模板全部版本化入库（`prompt_version`），风格漂移时能回滚
- **缓存感知布局（2026-09-06 增补，借鉴 AiChatTrpg CachedPrompt 三段式）**：组装时把 L1 基座放 system（跨回合字节稳定 = BP1）、L3 剧情记忆快照放前置 user 消息（记忆不变时稳定 = BP2）、L4 状态与 L5 会话窗口放尾部 user（每回合变化 = BP3），并用助手锚定消息划清 BP2/BP3 边界——前缀字节稳定可命中供应商 prompt 缓存，长团 token 成本显著下降。分层语义不变，只规定消息排布顺序
- **缓存命中实测与观测（2026-09-10）**：DashScope **隐式缓存自动开启**（无需 `cache_control`），实测同前缀第二次调用 `prompt_tokens_details.cached_tokens` = 9216/9275（**99.4%**）；最小可缓存前缀 1024 tokens 且**按 1024 分块**（短前缀只命中首块）。因此 `prompt_tokens` 只是**名义输入**，`llm_usage.cached_tokens` + `cache_hit_rate` 才是成本依据（设置面板显示"命中 N（命中率 X%）· 实际计费输入 = 名义 − 命中"）。**结论：不要加显式 `cache_control`**——规则是"以标记为终点向前回溯"，打在 system 上只能覆盖 system+tools（实测 3975，比隐式少一半以上）；若将来确需确定性缓存，标记应打在 **BP2 那条 user 消息**上（可覆盖 ~7500）。单次全自动调用体积实测：system 2317 字 + TOOL_SCHEMAS 6771 字 + BP2 4238 字 + BP3 3495 字 ≈ 9275 tokens，其中**约 75% 的字节跨轮稳定**
- **窗口可见性标注（2026-09-10）**：`secret` 消息（keeper 笔记 / 暗骰结果）与公开叙事同属 narrative 频道，进 L5 窗口时由 `assembler._session_line` 统一打「·仅KP」标记 + 段头警示（D8 是逐字替换，兜不住改写过的守秘内容，故靠标注让模型自己守边界）；`latest_action` 只取**玩家可见**消息——此前 `recent[0]` 会在"无新玩家/KP 消息"的触发下取到 AI 自己的守秘笔记

### 6.2 KP 风格系统（借鉴 coc-trpg-skill）

内置三种风格，实现为 **JSON 配置**而非写死在提示词里：

| 风格 | 叙事密度 | 规则解释 | 暗骰透明度 | 选项颗粒度 |
| --- | --- | --- | --- | --- |
| 剧情沉浸 | 高（多感官描写） | 低（只报结果） | 低 | 粗（开放式） |
| 规则教学 | 中 | 高（每次检定附规则说明，面向新手） | 高 | 细（手把手引导） |
| 平衡 Keeper（默认） | 中 | 中 | 中 | 中 |

- **风格只影响表达，不影响公平**：骰子永远由规则引擎产生，风格参数无权重改骰
- 支持用户自定义风格并保存（导出/导入 JSON），房间内实时切换且全员可见提示

### 6.3 每轮叙事输出协议（硬性格式）

LLM 每轮回复必须按四段结构输出（借鉴 coc-trpg-skill「跑团默认协议」），前端按结构渲染：

1. **当前状况**：结算本轮玩家行动与后果（含检定结果的剧情化叙述）
2. **已知变化**：只写玩家可知的线索、状态、NPC 反应（经 §6.4 过滤）
3. **行动切口**：给出 2-4 个具体可行的选项（编号仅用于引用，可点击）
4. **自由行动提示**：固定话术提醒玩家可自由描述行动

硬性原则（写入 L1 基座）：
- 玩家自然语言行动**优先于**预设选项
- 需要检定时，必须先说明「技能 / 难度 / 失败后果」再调用骰子工具
- **关键推论至少准备 3 条线索路径**，单次检定失败不卡死剧情
- 失败必须推进局势（制造代价 / 改变风险 / 揭示新信息），不允许「故事停止」
- 大成功 → 额外戏剧化奖励；大失败 → 有趣但不致命的惩罚 + 新突破口（借鉴 trpg-log-copilot GM 模式）
- PC 踢门/偏航 → 接受现状 + 软引导回主线，不强行拉回

### 6.4 信息可见性与防超游（借鉴 trpg-log-copilot）

三线分离，全链路贯穿（记忆、消息、线索、骰子都带可见性标记）：

| 层 | 内容 | 去向 |
| --- | --- | --- |
| public | 玩家可知的一切 | 剧情聊天框 |
| keeper | 真相、暗骰结果、NPC 动机、敌方行动 | 仅 KP 控制台 |
| ooc（场外） | 玩家闲聊、战术讨论、系统数值 | 玩家聊天框 |

防超游规则：
1. **LLM 输出必须经过可见性过滤器再分发**：任何 keeper 信息不得出现在 public 通道（这是防 AI 剧透的系统级保障，不依赖提示词自觉）
2. 暗骰（KP 骰 NPC 攻击 / 隐藏检定）默认 keeper 可见，KP 可手动公开
3. **推测 ≠ 事实**：玩家推理只标注为推测；NPC 证词标注来源与可靠度
4. 场外信息 KP 采纳时标注「来源：场外」，不伪装成角色发现

### 6.5 剧情记忆模型（五要素，综合两个 skill）

LLM 上下文由记忆模块**按需检索组装**，不把全文塞进 prompt。新增五类剧情状态：

| 要素 | 内容 | 可见性 |
| --- | --- | --- |
| 场景 scene | 当前地点 / 时间 / 在场者 / 氛围 | public |
| 实体 entity | 调查员与 NPC 的状态：公开状态与 KP 私有状态分开存 | 双份 |
| 线索 clue | 编号 / 内容 / 来源 / 指向 / 验证状态（pending→confirmed 或 excluded）/ 可见性 | 双份 |
| 伏笔 thread | 未结算事项、延迟 SAN、暗骰后果、待回收伏笔 | keeper 为主 |
| 时钟 clock | 威胁倒计时 / 追踪进度（如「教团仪式 3/4」） | 可配置 |

- 更新时机：场景推进 / 玩家决定 / 状态变更 / 获得线索 / 存档快照——**不做每轮全量写**（借鉴 coc-trpg-skill 的更新策略）
- 摘要压缩：剧情消息滚动窗口，场景结束触发摘要，**玩家版与 KP 版分开**（玩家摘要不含真相）
- 时间线精度：**不编造精度**——KP 没说的时刻不写时刻（借鉴 trpg-log-copilot 时间线规则）

### 6.6 NPC 卡模板（借鉴 coc-trpg-skill）

- 路人 NPC：一句话即可，不占上下文
- **核心 NPC 必备六要素**：公开身份 / 隐藏动机（keeper）/ 玩家可得线索 / 误导点 / 被逼问时的反应 / 死亡或离场替代方案（防剧情脆断）
- 来源：模组解析抽取（§6.8）+ LLM 按模板补全，存 npc 表，随剧情更新

### 6.7 Function Calling 工具集（LLM 的一切状态变更入口）

| 工具 | 说明 |
| --- | --- |
| `roll_check(skill, difficulty, bonus_dice)` | 技能检定，规则引擎执行 |
| `roll_dice(expr)` | 任意骰子表达式 |
| `san_check(target, loss_formula)` | 理智检定（联动疯狂表） |
| `secret_roll(..., hidden=true)` | 暗骰，结果只进 keeper 层 |
| `update_status(target, hp/san/mp, reason)` | 状态变更，**必须携带 reason**（溯源） |
| `get_card(target)` | 读取角色卡 |
| `add_clue / update_clue` | 线索登记与状态流转（含可见性） |
| `advance_clock(clock_id)` | 推进威胁时钟 |
| `set_scene(scene_desc)` | 场景切换 |

铁律：
- **LLM 禁止直接生成数值变更文本**——一切 HP/SAN/骰子变化必须走工具（防幻觉改数值，对应决策 D9）
- 工具调用失败（如技能不存在）返回错误让 LLM 澄清，禁止静默编造

### 6.8 模组结构化 schema（借鉴 worldbuilding）

模组解析（阶段 5）输出的 JSON 骨架，同时作为全自动主持的 L3 剧情层：

```json
{
  "title": "", "era": "", "背景概述": "",
  "核心异常": "一句话",
  "剧情链": [ { "节点": "", "类型": "开篇|调查|转折|危机|抉择", "地点": "", "NPC": [], "线索": [], "检定": [], "失败分支": "" } ],
  "三层冲突": { "表层": "", "深层": "", "终极": "" },
  "隐藏真相": { "表面设定": "", "异常线索": [], "揭露条件": "", "揭露后果": "" },
  "结局": [ { "条件": "", "描述": "", "SAN": "" } ],
  "npcs": [ "§6.6 模板" ],
  "时钟": [ ]
}
```

- 全自动主持以剧情链为**骨架**推进但不锁死：玩家偏航即兴展开，之后软引导回主线
- 内容边界：房间设置提供「内容尺度」选项，恐怖/血腥内容可淡化（借鉴 coc-trpg-skill 边界提醒）

### 6.9 提示词写作规范（借鉴 aaf-rulebook-editor）

- 「写规则像写法律」：每条指令明确**谁 / 何时 / 消耗什么 / 做什么 / 持续多久**，禁用「可能、或许、通常」等模糊词
- 规则不确定时让 LLM 声明「需查证」，**禁止编造规则书页码**
- 模板改动视为一次「发布」：跑一组固定剧情回归用例对比效果后再启用

### 6.10 落地位置

- 配置存储：KP 风格 / LLM 供应商 / 提示词模板 → SQLite + 可导出 JSON
- 开发节奏：L1+L2+输出协议与工具集（阶段 4 前半）→ 记忆五要素与可见性过滤（阶段 4 中段）→ 模组骨架驱动（阶段 5）

---

## 7. 分阶段实施计划

> 每阶段先做后端/逻辑、再做界面、最后联调自测。**每个阶段结束必须能跑通验收标准**再进入下一阶段。

### 阶段 0：工程初始化（0.5 天）

- [x] 安装环境：Node 18+ 与 pnpm；Python 3.11+ 与 venv/poetry；Git
- [x] 创建目录结构（见 §8）：`project/frontend`（Vue3）与 `project/backend`（FastAPI）
- [x] 前端：`pnpm create vite` → Vue3 + TS 模板，接入 Pinia / Vue Router / Element Plus，配置 ESLint + Prettier
- [x] 后端：FastAPI + SQLModel + uvicorn，建 `main.py` 提供 `/api/health` 健康检查
- [x] 前后端联通 Demo：前端页面调用 `/api/health` 显示后端版本；配置 Vite 代理
- [x] Git 初始化仓库，写 `.gitignore`（node_modules/venv/*.db/__pycache__），首次提交
- [x] **验收**：`pnpm dev` + `uvicorn main:app` 同时启动，浏览器能看到前后端联通的页面

### 阶段 1：数据模型与 API 契约（1 天）

- [ ] 打开 `coc七版规则空白卡.xlsx`，逐 sheet 整理字段清单，确定角色卡 JSON schema（TypeScript interface + Python Pydantic 双份定义，字段一一对应）
- [ ] 从规则书 PDF 查证并记录核心公式与检定规则（HP/MP/SAN/DB/MOV、困难/极难阈值、大成功大失败条件、奖励骰惩罚骰、对抗检定）写入 `docs/coc7-rules.md`
- [ ] SQLModel 建表 + 生成 SQLite 文件；写迁移约定（早期直接删库重建，表结构稳定后再考虑迁移工具）
- [ ] 编写 REST API 契约文档 `docs/api-contract.md`（路由、请求响应示例）+ WS 消息协议定稿
- [ ] 用 160+ 职业表与技能基础值表制作种子数据 `backend/app/seed/`（可从 xlsx 用脚本导出 JSON）
- [ ] **验收**：`/docs` 页面能看到全部 API；运行 seed 脚本后数据库有职业/技能数据

### 阶段 2：角色卡模块 ✅ 已完成（2026-09-05，浏览器实测通过）

- [x] 后端规则引擎 `rules/coc7.py` + `rules/dice.py`（纯函数）：属性生成 / 衍生值 / DB·MOV 查表 / 检定判定（奖惩骰净抵消、大失败按难度目标值）
- [x] 职业点数 `rules/occupation.py`：点数公式数据驱动（Σ属性×系数 + "或"选择 pending 机制）/ 分配校验 / 信用评级区间校验
- [x] 单元测试 14 用例（tests/）全绿；API 冒烟脚本 `scripts/_probe.py`
- [x] API：`GET occupations(+{id}详情)` / `skills` / `cards(+{id})`、`POST cards`（技能点+信用评级校验、技能基础值后端权威化）、`POST cards/budget`（预算预览）、`POST dice/attributes`（属性生成）
- [x] 前端：建卡向导三步（基本信息+职业 → **投点法/购点法双模式** → 技能分配含分类技能二级选择+自定义命名+信用评级输入）、列表页、详情页（整卡展示，技能当前值计算）
- [x] **验收**：浏览器模拟用户走完三步向导建卡（张三/会计师）→ 201 → 详情页数值全对；pytest 14 绿

### 阶段 2.5：建卡体验完善（推迟项，阶段 3.4 后或碎片时间做，不阻塞 MVP）

- [x] 删除角色卡：`DELETE /api/cards/{card_id}`（204/404）+ 列表页删除按钮 + 确认框
- [x] 详情页信用评级展示；技能二级选择 / 自定义技能命名 / 投点购点双模式（已随阶段 2 完成）
- [x] 卡片编辑 `PATCH /api/cards/{card_id}`：背景八要素 / 随身物品（文本）/ 武器（武器数据从 `other/table/coc七版武器列表.txt` 抄录入 seed，标准表选 + 自定义）
- [x] free_picks 任意特长本职（向导 UI 已诚实标注"下一迭代"）
- [x] 检定骰子结果动画（普通/困难/极难/大成功/大失败不同颜色）
- [x] 后端建卡校验补强：购点法 Σ=460 与单项 15~90 的服务端校验（当前仅前端拦截，`Attributes` schema 仍是 ge=0 le=400）

### 阶段 3：局域网真人团（★ MVP 核心，3-4 天）

> **MVP 定义**：局域网内 1 个 KP + 2~4 个玩家，用浏览器开一局真人 CoC 团。
> 真人流程是阶段 4"人机协同主持"的子集——先跑通真人，Agent 才有挂载点（聊天流/骰子事件/角色卡上下文都是 Agent 的输入）。
> 取舍尺子："少了它，一局团还能不能开？"——不能开才做，能开就推迟。

**界面布局**：

```
玩家 /room/:id（两栏）                     KP /room/:id/kp（三栏）
┌─────────────────────┬────────────────┐  ┌──────────┬──────────────────┬──────────┐
│ 剧情聊天流            │ 我的角色卡（侧栏）│  │ 玩家面板  │ 剧情聊天流         │ KP 工具箱 │
│ ├ KP 剧情描述（高亮）  │ ├ 姓名/职业/年龄 │  │ ├ 成员列表 │ （同玩家视图，     │ ├ 掷骰面板 │
│ ├ 骰子结果（彩色徽章） │ ├ HP/MP/SAN 当前 │  │ ├ 点开整卡 │  多 KP 发剧情视角）│ ├ 暗骰(仅KP)│
│ ├ 玩家行动描述        │ ├ 属性/技能列表   │  │ ├ HP/SAN ├──────────────────┤ ├ 扣HP/扣SAN│
│ ├ 系统提示(加入/离开) │ ├ [技能检定]按钮  │  │ │ 红条预警│ 底部：剧情输入框    │ ├ 场景标题栏│
│ └ 底部行动输入框      │ └ 背景故事(折叠)  │  │ └ 卡片变更│                    │ └ 存档/读档 │
│   [tab: 玩家闲聊 OOC] │                 │  └──────────┴──────────────────┴──────────┘
└─────────────────────┴────────────────┘
```

- 不做"回合确认"按钮：KP 发剧情即推进；改为**场景标题栏**（地点/时间，KP 可编辑、全员可见）——它同时是阶段 4 Agent 的场景上下文。
- 最小交互集（7 个）：KP 建房 → 给链接/房间号 → 批准加入 → 发剧情 → 暗骰 → 改玩家 HP/SAN → 存档；玩家加入（名字+选卡）→ 发行动 → 闲聊 → 技能检定 → 看自己卡。

#### 3.1 房间与 WS 骨架（1 天）

- [x] `models.py` 建 `room` / `room_member` 表（§5.2 已规划）——另按 WS 落库需要同步建了 `message` 表
- [x] REST：`POST /api/rooms`（KP 建房，返回房间号）/ `POST /api/rooms/{id}/join`（玩家名 + 角色卡 id）/ `GET /api/rooms`（列表）
- [x] `app/ws/`：连接管理（room_id → 连接组）、`join_room` / `chat_send` / `chat_new` 三种消息、按房间广播
- [x] 前端 `/room/:id` 玩家双栏聊天（先玩家视角，消息区分 剧情/闲聊/系统）
- [x] **验收**：两个浏览器窗口加入同一房间，互发消息实时可见（chrome-devtools 双页面实测，2026-09-05）

#### 3.2 掷骰进聊天流（1 天）

- [x] `POST /api/dice/check` → 规则引擎 `check` → 落 message 表（type=dice）→ `roll_result` 广播（payload 带技能名/骰值细节/成功等级/目标值，前端彩色徽章）；MVP 技能值由请求携带 value
- [x] 玩家侧栏技能检定面板（绑卡选技能下拉 / KP 无卡手输技能名+数值 + 难度三选）
- [x] KP 暗骰：广播带 `secret: true` 标记，前端 store 按 `secret && 非 KP` 过滤渲染（协议层仍到达玩家连接，3.3 评估收紧为服务端定向发送）
- [x] **验收**：A 掷「图书馆使用 55」双方实时出现彩色徽章（掷出 8 → 极难蓝）；KP 暗骰「侦查 50」仅 KP 可见（2026-09-05 chrome-devtools 双页面实测，console 无报错）

#### 3.3 KP 控制台（1-2 天）

- [x] 按角色渲染 KP 三栏视图（`/room/:id/kp` → KPConsoleView：左玩家面板 / 中剧情聊天流（ChatStream 组件复用）/ 右 KP 工具箱；KP 建房与加入直跳 /kp，非 KP 访问由视图内 REST 守卫弹回）
- [x] 玩家面板：成员卡片（名字/职业/HP·SAN 条）、点开 el-drawer 拉整卡、HP/SAN ≤30% 红色预警（条变红 + 卡片红边 + 预警标签）
- [x] KP 改玩家 HP/SAN（`POST /rooms/{id}/status`：绝对值 + 服务端 clamp + reason 必填（D9）→ 落 message（type=status）→ `status_changed` 广播；玩家侧栏与 KP 面板由 cardStates 快照驱动实时变化）
- [x] 场景标题栏（room 表加 scene_title/scene_desc；`PUT /rooms/{id}/scene` KP 校验 + sys 消息落库 → `scene_changed` 广播；双方顶栏 chip + GET /rooms/{id} 进房恢复）
- [x] 暗骰收紧为服务端定向发送（D8 收尾）：`manager.broadcast_to_roles` 按 room_member 花名册只发 KP 连接，玩家协议层收不到信封；前端 secret 过滤保留作兜底
- [x] **验收**：KP 扣「张三」HP → 玩家侧栏血条实时变化、KP 面板 ≤30% 红警；KP 暗骰玩家连接 0 信封（WS 探针实测：secret 掷骰 0 收到 / 明骰正常到达）；KP 改场景双方可见；玩家访问 /kp 被弹回（2026-09-05 浏览器双页面实测，接口冒烟 12 项全过）

#### 3.4 存档与断线重连（1 天）

- [x] WS 心跳 + 断线自动重连 + `room_state` 全量补齐（消息 seq 序号）
- [x] `save_game`：KP 一键存档/读档（房间状态快照：成员+卡状态+聊天历史）
- [x] 消息历史持久化（`message` 表，按房间检索）
- [x] **验收**：B 断网 10s 重连后消息与状态完整；存档→重开→读档恢复

**阶段 3 完成即 MVP 达成** → 进入阶段 4（Agent 挂载到现有按钮与聊天流上）。

### 阶段 4：LLM 集成、Agent 配置与双模式主持（★ 系统灵魂，4.1~4.4 共约 5 天；2026-09-06 拆分）

> **拆分理由**：3.1~3.4 已把 D8（暗骰定向）/ D9（状态变更带 reason）两大铁律做成基础设施，工具层多为薄包装；按"每个小阶段可独立跑通验收"拆分，避免五层提示词 + 记忆五要素 + 双模式的大爆炸交付。
> **顺序决策（D10）**：协同模式先于全自动——LLM 无写权、不碰骰子、无需可见性过滤（建议只进 KP 屏幕），是风险最低的"LLM 进房间"路径，且 KP 控制台（3.3）是现成挂载界面，还能先验证提示词质量。

#### 4.1 LLM 适配层 + 协同建议模式（1.5 天）✅ 已完成（2026-09-06，浏览器双页面实测通过）

- [x] `llm/provider.py`：OpenAI 兼容客户端（openai SDK AsyncOpenAI），配置化供应商（`.env` + `llm/providers.py` 供应商预设注册表与 key/base_url 自动识别，借鉴 ccswitch：智谱 GLM / DeepSeek / 百炼千问 / OpenAI 四家预设），超时 30s + 2 次重试 + 失败降级（`LLMUnavailableError` 分类 → 回退纯人工并提示 KP）；base_url/api_key/model 读 `backend/.env`（llm_config 表与 KP 设置页后置 4.4，决策 D10）；实测千问（DashScope compatible-mode + qwen-flash）通过
- [x] 最小提示词组装器 `agent/assembler.py`：独立模块，L1 基座（`agent/prompts/l1_base.py` 版本化 l1-v1：CoC7 KP 行为准则 + 协同建议输出协议 + 检定速查）+ L5 会话滚动窗口（最近 20 条 narrative）；L2/L3/L4 以可选字段预留；建议 JSON 容错解析（剥围栏/截取/字段规整）
- [x] **协同模式**：玩家在剧情频道行动 → WS chat_send 自动触发后台生成（单飞+合并，不阻塞聊天）→ 2~3 条候选建议经 `suggestions` 信封**只定向广播 KP**（D8 同款定向）；KP 控制台 AI 建议面板可采纳/编辑/重生成（focus 附加指令）/完全手写，采纳与编辑走现有 chat_send 通道；模式开关 `PUT /rooms/{id}/agent-mode`（manual/collab，sys 消息 + agent_mode_changed 全员广播）；连续 3 次失败自动回退 manual + 系统提示；另加 `GET /llm/status`、`POST /llm/test`（连通性自检）
- [x] **验收**：断网 LLM 自动降级（降级横幅 → 连续 3 次失败自动切回纯人工 + 系统消息）；KP 采纳/编辑建议出现在剧情流（双端同步）；建议生成不阻塞聊天（生成期间消息/OOC/面板均正常）；关闭模式后不再触发生成——浏览器模拟用户全程实测，截图 4 张入 gui-test-screenshots/

#### 4.1+ 修订清单（2026-09-06 首版代码评审 + 开源项目经验吸收）✅ 已完成（2026-09-06，含可选三项；pytest 73→104 全绿 + 浏览器双页面验收通过，截图 41-6~41-13）

> 评审结论：4.1 架构方向正确（单一 OpenAI 兼容客户端 + 供应商注册表 + 单飞合并 + 连败降级 + 建议只定向 KP），与 AiChatTrpg / trpg-workbench 两个大型开源项目实测经验一致，**不需要重写**。以下为具体修订项。

- [x] **模型预设刷新 + 实时探测替代静态表**（P1，已联网核实）：智谱现役 GLM-5.3 系列（GLM-5.3-flash与GLM-5.3），presets 里的 glm-4-flash/glm-4-plus/glm-4-air 已失效；DeepSeek 2026-07-24 下线 deepseek-chat/deepseek-reasoner 旧名、改 v4 命名（pro与flash）——建议写的预设模型url都先搜索官网找文档填写，不要自己编。静态 models 表追不完——改为「静态推荐（仅 label/base_url）+ `GET /llm/models` 实时探测（`client.models.list()`）+ 手填兜底」，不自建模型目录库（workbench 撤掉模型目录 DB 是教训）。落地：providers.py 预设刷新（glm-5.3-flash/glm-5.3、deepseek-v4-pro/deepseek-v4-flash、gpt-5-mini/gpt-5.2）+ provider.list_models()（单次尝试 10s 超时）+ GET /api/llm/models + /llm/status 透出 presets；test_preset_models_are_current 锁现役名防再过期不察觉
- [x] **key 形态启发式降级为仅供参考**：智谱新 key 格式需实测（id.secret 正则可能已不匹配）；host 匹配保留，key 形态判断不得参与任何关键路径（现状仅影响 /llm/status 展示，维持此定位）。落地：providers.py 注释与 key_hint 更新，识别逻辑未动
- [x] **最小 KP 设置面板（建议从 4.4 提前）**：`/llm/status` 与 `/llm/test` 端点已就绪，只差前端——base_url/key/model 表单 + 连通性测试按钮（返回延迟）+ 模型探测下拉 + 手填兜底；key 永不回传明文（掩码）；存储仍走 .env，DB 入库留给 4.4。落地：后端 PUT /api/llm/config（update_env_file 行级改写 .env + reload_settings 热重载：pop LLM_* 环境变量再 override 重读；api_key 空=保持现有）+ 前端 LlmSettingsDialog.vue（预设 chips 快捷填充 / 掩码 placeholder / 探测下拉 allow-create 手填 / 脏表单先保存确认）挂 KP 工具箱「LLM 设置」面板
- [x] **同步 DB 查询移出事件循环**（P2）：suggest.py `_collect_context` 用 `asyncio.to_thread` 包装，防 SQLite 写锁期间阻塞 WS 心跳/聊天广播（含 scenario_brief 文件读）
- [x] **deadline 预算自洽**：DEFAULT_DEADLINE=75s < 3×30s+退避 2.4s≈92s，第三次重试恒被裁——改为按 attempts×timeout+退避余量动态计算，或明示"预算优先"并去掉末次尝试。落地：`_compute_deadline(attempts, timeout)`（默认 3×30+2.4+1≈93.4s），deadline=None 时自动计算
- [x] **裸 create_task 加异常回调**：suggestions.py 与 suggest.py 两处 fire-and-forget 加 done-callback 记日志，防非预期异常静默消失。落地：新增 app/tasks.py `spawn_background()`（取消静默、异常记 error 日志），实际替换 3 处（REST 手动触发 / WS 自动触发 / 引擎 pending 补跑）
- [x] **temperature 黑名单守卫**：推理模型（o1/gpt-5 系等）拒绝 temperature 参数，请求前按模型名过滤（借鉴 AiChatTrpg `_model_rejects_temperature`：gpt-5/o1/o3/o4 前缀 + 含 codex）
- [x] **ping 不走完整重试链**：chat() 加 attempts 覆盖参数，ping 传 1（否则服务宕机时测试按钮等满 deadline）
- [x] （可选）自动触发加 2~3s 静默期 debounce：玩家停止打字才生成，控长团 token 成本（单飞合并已防并发、未防频率）。落地：SuggestionEngine.schedule_auto_generate（AUTO_DEBOUNCE_SECONDS=2.5，静默期内新消息取消重排；手动触发/切模式/降级时 cancel_auto），WS chat_send 改走该入口
- [x] （可选）`response_format={'type':'json_object'}`：GLM/DeepSeek 均支持，降低 JSON 解析失败率；保留修复重问兜底。落地：chat() 加 json_mode 参数，供应商 400 拒绝 response_format 时同轮次自动去参重试一次；建议生成与修复重问均启用
- [x] （可选）Mock LLM 客户端：无 key 可跑通全流程 UI/演示（几十行），比赛断网兜底同样受益。落地：app/llm/mock.py，`LLM_MODEL=mock` 即启用（settings.mock_mode、enabled 放宽），get_client() 返回 MockLLMClient（从提示词截取最新推进生成合法建议 JSON）；/llm/status 带 mock_mode，设置面板显示「演示模式」标签

#### 4.2 Function Calling + 全自动主持 MVP（1.5~2 天）✅ 已完成（2026-09-06；pytest 104→148 全绿 + 浏览器双页面验收通过，截图 42-1~42-6；流式输出为可选项，跳过以保持与 4.1 一致的非流式架构）

- [x] **Function Calling 工具集（§6.7）——薄包装既有服务**：roll_check / roll_dice → `rules/coc7.py`；update_status（必须带 reason）→ 3.3 status 逻辑；secret_roll（暗骰）→ `broadcast_to_roles` 定向（D8）；set_scene → 3.3 scene API；LLM 禁止直接生成数值变更，工具失败必须澄清（D3/D9 铁律不变）。落地：`app/agent/tools.py`（8 个工具 schema+执行器，错误一律 `{"error":...}` 回喂）+ `app/agent/state_ops.py`（kp.py status/scene 主体抽出共享，REST 与工具完全同构）+ `provider.chat_with_tools()`（AssistantTurn，复用重试/deadline/temperature/json_mode 基建）+ MockLLMClient 工具循环脚本化
- [x] 规则库常量前移（原阶段 5 项）：从守秘人规则书 PDF 抽取理智损失表、疯狂症状表做成 JSON 常量，供 san_check 联动疯狂状态。落地：`scripts/extract_madness_tables.py` 从 docs/coc7-rules.md（阶段 1 已对 PDF 核实）解析生成 `app/rules/data/madness_tables.json`（即时/总结症状 1D10 + 恐惧/躁狂 D100 共 220 行，行数校验）+ `app/rules/sanity.py`（损失公式解析「成功/失败」、大失败取最大值、三种疯狂判定——临时疯狂「INT 检定成功=发疯」反直觉规则、不定疯狂按当日累计 1/5 SAN、永久疯狂，症状表联动查找）
- [x] **四段叙事输出协议（§6.3）**写入 L1 基座；前端按结构渲染，「行动切口」选项可点击发送，自由输入优先。落地：`l1_base.AUTO_PROTOCOL`（l1-v2-auto 版本化）——narration_public（当前状况+已知变化）/keeper_notes（KP 私密）/options（2~4 条）；前端 ChatStream 渲染「AI 主持」蓝 chip + 公开叙事 + 可点击行动切口 + 固定自由行动提示
- [x] **信息可见性与防超游过滤（§6.4）**：LLM 输出经可见性过滤器分发，keeper 信息不进剧情聊天框（本阶段唯一全新安全组件）；暗骰默认 KP 可见可手动公开；场外采纳需标注。落地：终稿结构化双通道 = narration_public 走 `Message(secret=False)`+chat_new 全员广播、keeper_notes 走 `Message(secret=True)`+`broadcast_to_roles({'kp'})`（复用 3.3 暗骰机制，玩家协议层收不到）；history 端点收紧为 secret 行一律仅 KP（原只过滤暗骰）；前端 store 非 KP 兜底丢弃 keeper 行 + 紫色「仅 KP」专享样式
- [x] `scenario_state` 表（场景快照）先顶住剧情上下文；clue/thread/clock/npc 后置 4.3。落地：`ScenarioState(room_id PK, data JSON)`——{scene（set_scene 双写）, events（record_events 滚动 ≤20 条）, san_today（san_check 累加，不定性疯狂判定用）}
- [x] **提示词按缓存感知布局组装（§6.1 BP1/BP2/BP3）**：L1 基座放 system（字节稳定），L3 记忆快照放前置 user（记忆不变时稳定），每回合变化的 L4/L5 放尾部 user + 助手锚定消息边界——长团命中供应商 prompt 缓存，token 成本大幅下降（借鉴 AiChatTrpg `CachedPrompt` 三段式）。落地：`assembler.build_auto_messages(AutoContext)`——BP1=system、BP2=[剧情记忆]（模组骨架+场景，仅 set_scene 时变）+锚定、BP3=[本回合]（事件登记+调查员含技能表 top40+会话窗口+最新行动）+锚定+最终指令；事件每轮变故置 BP3，4.3 场景级摘要落地后再并入 BP2（代码注释已记取舍）
- [x] （借鉴 AiChatTrpg「提案→校验→确认」契约）LLM 产出的状态变更先以提案对象存在，经工具执行/规则引擎确认后才生效；叙事文本不是权威。落地：即 function calling 本身——LLM 只能以 tool_call「提案」，`execute_tool` 经规则引擎/规则书常量执行后才落库广播，四段叙事仅引用已结算结果（浏览器实测正文无骰点数字）
- [x] （可选）全自动叙事走流式输出（WS 分片）+ 15s keepalive 防代理断连（借鉴 workbench SSE 心跳）——**跳过**（标题栏已注明：保持与 4.1 一致的"生成不阻塞聊天"非流式架构，4.4 后按需补）
- [x] **验收**：全自动跑通"探索→检定→暗骰→扣SAN"一段剧情，全程无剧透泄漏、无数值幻觉。实测（qwen-flash + 《八月二十二日》模组骨架）：玩家行动→AI 自主 san_check（理智 59 掷 35 成功损失 0 徽章+状态行）→KP 插话引导→AI secret_roll 暗骰 1D6→5（仅 KP 紫行）+ san_check 失败损失 4（SAN 59→55 玩家血条实时变化）+ set_scene 场景 chip 更新；玩家端 keeper/暗骰零元素（DOM 断言 0）；mock 模式全流程（检定→叙事→选项点击→下一轮）可演示；改坏 base_url 三连败自动回退 manual；keeper 笔记含模组递进建议（无头电车/深渊站台/1D3→1D6 递进）

#### 4.3 剧情记忆五要素 + 线索系统（1 天）

- [x] **剧情记忆系统（§6.5/§6.6）**：clue / thread / clock / npc 四张表落地（models.py）；新工具 add_clue / update_clue / add_thread / resolve_thread / advance_clock / upsert_npc 挂进 TOOL_SCHEMAS；L3 层记忆快照注入 BP2（KP 全知视角，线索带可见性标记），不做每轮全量写（2026-09-06，AI 代写；**新增表需删库重建 `scripts/init_db.py --force`**）
- [x] **D8 系统级兜底过滤**：`keeper.filter_final_visibility` 纯函数——公开叙事与行动选项中出现的 keeper 专属片段（仅KP线索编号 / keeper时钟名 / 未结算伏笔 / NPC 隐藏动机）强制替换占位符并转入 keeper_notes，分发前强制执行（不依赖提示词自觉）
- [x] 场景结束触发双份摘要（玩家版不含真相 / KP 版）：set_scene 触发后台 best-effort LLM 摘要，存 scenario_state.data['scene_summaries']（滚动 5 条），玩家版摘要入 BP2 跨场景记忆
- [x] NPC 卡生成与维护：核心 NPC 六要素模板（公开身份/隐藏动机/玩家可得线索/误导点/被逼问反应/离场替代方案），upsert_npc 按名字建档/更新，status=gone 标记离场
- [x] **验收**：跨场景对局中 LLM 能引用此前登记的线索与 NPC 状态；玩家侧摘要不含 keeper 信息（2026-09-07 浏览器双端十轮实测通过：KP+玩家双上下文、完整建卡含背景/随身物品/武器；agent 正确读取模组骨架/角色卡技能/每轮行动，检定下放/理智损失/SAN 扣减全链路工作，跨轮伏笔（药袋/针痕/8.22/莲荷町#2201）持续回收，玩家屏无 keeper 泄漏）

#### 4.4 KP 风格系统 + Token 治理（0.5~1 天）✅ 已完成（2026-09-08；pytest 167→180 全绿 + 浏览器双端实测验收线全通过，qwen3.8-max 主叙事 + qwen3.8-flash 轻任务）

- [x] **KP 风格系统（§6.2）**：剧情沉浸 / 规则教学 / 平衡 Keeper 三种风格 JSON（四旋钮：叙事密度/规则解释/暗骰透明度/选项颗粒度 + 自由 note），L2 层注入（collab 拼 system、auto 放 BP2 作废记忆段缓存不动 BP1），房间设置实时切换（PUT /rooms/{id}/kp-style → sys 消息落库 + kp_style_changed 全员广播），自定义风格 kp_style 表保存/删除（引用房间自动回退 balanced）/导出导入 JSON；前端 KpStylePanel.vue（下拉分组选风格 + 自定义管理弹窗四旋钮编辑 + JSON 导入导出 + 删除确认）
- [x] llm_config 入库 + KP 设置页（从 .env 迁移）：llm_config 表单行 id=1 权威（首次无行从 .env seed，此后 .env 不再是运行时来源），设置面板写 DB；**分级模型路由（轻量）**：light_base_url/api_key/model 三字段配置轻任务模型（建议生成/场景摘要走 get_light_client()，留空=跟随主模型）；**token 消耗统计**：provider._complete 真实响应记账（mock 不计，失败不影响主流程），LlmUsage 单行总账随 /llm/status 透出，设置面板显示全局累计
- [x] 4.3 遗留修复：① AI 偶发绕过 request_check 代掷 → roll_check 带 target 工具层硬拦截（ValueError 引导 request_check，schema 移除 target）；② 降级后 keeperPending 残留 → keeper._handle_failure 每次失败同步广播 suggestions 降级信封，前端据此清骨架；③ 分级路由消解 qwen3.8-max 延迟波动
- [x] provider 健壮性（实测驱动）：DeepSeek-v4-pro 推理模型设 max_tokens 反而触发异常长思考吃满预算（content 空）→ 调用方默认不传 max_tokens（实测不传时思考 41 tokens 级、3s 收敛），预算翻倍重试仅作显式传值时的兜底；ping max_tokens 8→64（思考也计入 completion 预算）
- [x] 存量库迁移脚本 scripts/migrate_44.py（room 补 style_id 列 + 新表 create_all，不动旧数据）
- [x] **验收（阶段 4 总验收）**：✅ 切换风格叙事肉眼可见（沉浸=多感官高密度，教学=检定后明确讲解规则依据如「极难成功（8/80）」）；✅ 协同/全自动随时切换；✅ 全自动完整验收线实测打通：探索→检定下放（3 次 request_check 玩家本人投掷，服务端按卡查值）→暗骰（多次仅 KP 可见）→扣SAN（san_check 掷 11 困难成功损失 1，SAN 27→26 玩家血条实时）→线索登记（线索-01~06）→时钟推进（雾中看守逼近 1/4→4/4 走满触发看守现身），全程玩家端 DOM 断言零 keeper 泄漏；✅ 断网三连败自动回退 manual + 系统消息；✅ 协同建议由轻任务模型生成（payload model=qwen3.8-flash）；✅ Token 总账 UI 显示（52 次 / 460.2k 输入 / 68.8k 输出）

### 阶段 5：模组解析（2 天）✅ 已完成（2026-09-10）

- [x] 模组上传 API：支持 TXT / PDF / DOCX（Python 提取纯文本）——`POST /api/modules`，DOCX 走标准库 zipfile+XML，PDF 走 pypdf，TXT/MD 带编码链回退
- [x] LLM 结构化抽取：分块喂给 LLM，抽取→模组标题/背景/基调/开场钩子/分幕/NPC（六要素+数值）/线索/时钟/结局/关键检定/存疑项，固定 JSON schema 存库（`module_scenario.parsed`）
- [x] 模组库页面：列表（状态徽章/来源格式/所用模型）/ 上传 / 查看（原文检索 + 结构化分块折叠 + 就地编辑校对）/ 删除
- [x] 全自动主持模式可选择一个已解析模组作为剧情骨架（注入系统提示词）——协同 L3 与全自动 BP2 共用 `load_module_brief`，未挂载回退 `scenario_brief.txt`
- [x] 规则库：理智损失表、疯狂症状表已**前移至 4.2**（san_check 依赖）；伤害表等其余高频规则随需补抽
- [x] **验收**：真实模组（《雪盲》DOCX + 《八月二十二日》PDF）上传 → 结构化 JSON 通过 → 模组挂载后 AI 按模组 NPC/线索/时钟主持，玩家端零剧透（详见 §11 2026-09-10 两行）
- 实施决策（用户 2026-09-10）：① 结构化结果**支持人工编辑修正关键字段**（PUT 局部覆盖）；② 一个房间同时只挂 1 个模组，可换绑/解绑；③ **手动点「开始解析」且可选解析模型**（上传只提取文本，不自动花钱）

### 阶段 6：打磨与演示（**2026-09-10 重写 / 6.2 于 2026-09-11 按样例图细化**，4~5 天）

> 重写理由（用户 2026-09-10 决策）：原计划（2 天 5 条）写在阶段 4 之前，现在回头看**方向对但偏薄**——
> ① 漏了 UI 美化（用户明确要求纳入本阶段：现有 UI "能用但不好看"，这是演示的第一印象）；
> ② 漏了阶段 1~5 积累的遗留与安全项（WS 叙事频道全员可发、全局资源无鉴权、服务端组选择校验未接线等）；
> ③ 部署只写了一句"一键脚本"，而演示必须**单端口**（现在仍是 5173+8000 双端口，外行跑不起来）；
> ④ 缺少可执行的性能口径与质量基线。故重写为 6 块，并明确"演示前必做"的优先级。

#### 6.1 部署与分发（★演示前必做，0.5 天）✅ 已完成（2026-09-11）
- [x] **单端口托管**：前端 `npm run build` 产物由 FastAPI `StaticFiles` 托管 + SPA fallback（`/assets/*` 静态、其余回 `index.html`），开发仍走 Vite 代理。落地：`app/static_hosting.py`（`mount_spa()`：dist 缺失静默跳过、幂等、`/api` 与 `/ws` 前缀不被回退吃掉、防目录穿越、index.html 带 `no-cache`），`main.py` 在所有路由注册后挂载
- [x] `start.bat` 一键启动：检测 Python/Node → 建 venv 装依赖 → 建库/迁移 → 起后端 → 自动开浏览器；端口占用与缺依赖要给人话提示。落地：`start.bat`（纯 ASCII 引导壳，**不调用 chcp**，见下）+ `scripts/bootstrap.py`（全部中文交互与判断；venv 缺 pip 自动 ensurepip 自愈、依赖按 stamp 判定不无脑重装、存量库跑 44~47 幂等迁移、`--check` 自检模式、`--rebuild` 强制重建、局域网地址按默认路由网卡优先打印）
- [x] `.env.example` + 首次配置向导（没配 key 也能进 mock 模式演示）。落地：`.env.example` 重写（首次配置三条路径 / llm_config 为 DB 权威 / mock 与运行时参数 / light_* 只能走设置面板）+ 大厅引导条 `components/LlmFirstRunGuide.vue`（未配置时亮出「启用演示模式」一键写 `model=mock` 与「去配置」两个出口）
- [x] 《部署文档》（目标：全新机器 10 分钟跑起来）与《使用说明》（KP 视角 + 玩家视角）。落地：`docs/部署文档.md`（环境准备 / 一键启动 / 局域网开团 / 模型配置 / 手动启动 / FAQ / 演示前清单）、`docs/使用说明.md`（KP 三栏与各面板 / 玩家建卡与桌上操作 / 收场 / 常见疑问）
- [x] **验收**：真实构建 + 单端口实测（`/`、`/room/XXXX/kp` 均回构建后的 index.html，`/assets/*.js` 200 `application/javascript`，未知 `/api/*` 回 JSON 404，`/docs` 正常）；`start.bat --check` 五步全过；模拟用户双击（控制台初始码页 936）下中文提示无截断；pytest 292→305 全绿（新增 `tests/test_static_hosting.py` 12 例）+ vue-tsc 通过
- **踩坑记录（2026-09-11，勿回退）**：cmd.exe 读取 UTF-8 批处理文件时，若文件内执行了 `chcp 65001` 而**控制台初始代码页不是 65001**（用户双击就是新控制台 CP936），会发生**行读取错位**——中文注释行的后半截被当作命令执行（实测 `'数据库' is not recognized as an internal or external command`）；同一文件在 CP65001 控制台里运行却完全正常（非确定性复现）。故 `start.bat` 保持**纯 ASCII 且不调用 chcp**，中文输出与逻辑全部移入 `scripts/bootstrap.py`（由它用 `SetConsoleOutputCP(65001)` 设置编码）

#### 6.2 UI 重构美化（★用户要求，2026-09-11 按样例图重写，约 3~4 天）

> **视觉基线**：`other/前端样例.png`——克苏鲁暗色主题：全屏暗色氛围背景、发光描边面板卡片、顶部品牌栏（logo/局域网徽章/主持模式开关/设置/全屏）、左侧导航侧栏（底部收房间信息卡与结束游戏）、中央剧情流为主角（模组标题+序章横幅、角色列表卡片化、消息气泡分级）、右侧工具栏（检定与投点 / 理智与疯狂 / 聊天频道 分组面板）。
> **范围铁律**：只重做观感与布局，**不改任何业务逻辑、消息协议与 store/api**（样例图每个功能均已存在，只是长得不一样）；不强求逐像素复刻按钮与文案，功能映射到现有功能即可。预计 85% 观感可达成（EP 暗色 + 令牌定制），逐像素复刻不做。

> **编号说明（2026-09-11 追加）**：原 9 小项拆为 10 小项——插入「④ 系统设置页」（用户要求的新模块：背景图自选 + 音效 + AI 配置收编），原 ④~⑨ 顺延为 ⑤~⑩；同时把「消息流视觉统一」提到 ⑤，因为 `ChatStream.vue` 是房间页与 KP 控制台共用的同一个组件，先统一气泡再重排两侧布局可少改一遍。

- [x] **① 设计令牌 + 全局主题地基**（其余小项的前提，先行）：CSS 变量色板（暗色背景层级/主色/成功失败/警示/发光描边）/间距/字号/圆角/阴影，替换散落在各组件 `<style scoped>` 里的魔法色值（现在改一处要满地找）；Element Plus 切官方暗色主题并按令牌定制（表格/标签/弹窗/下拉），清理零散 `:deep` 覆写（2026-09-11 完成：`assets/styles/{tokens,global,animations}.css` + `main.ts` 接 EP 暗色，浏览器实测 html.dark/主色/弹窗均生效）
- [x] **② 全局应用外壳**：顶部品牌栏 + 左侧导航侧栏抽成 Layout 组件挂 router（大厅/当前房间/角色管理/模组库/系统设置）；房间信息卡（房间号/人数/模式/进行时长）与「结束游戏」收进侧栏底部；主持模式开关（全自动/协同/人工）上提至顶栏（2026-09-11 完成：`layouts/{AppLayout,AppTopBar,AppSideNav,RoomInfoCard,ModeSwitch}.vue` + `components/common/CocIcon.vue`，`App.vue` 只挂外壳；模式开关上提顶栏、`AiSuggestionPanel` 改只读；`/settings` 并入 `ROOM_SCOPE_ROUTE_NAMES`）
- [x] **③ 背景与品牌素材**：暗色氛围背景图 + 模组封面占位图 + logo/favicon（AI 生图 2~5 张或 CSS 渐变兜底，进 `assets/`，单图 <500KB）；素材缺失不阻塞布局（渐变先行）。**6.1 实测遗留**：`public/` 为空 → `/favicon.ico` 目前回退到 index.html（浏览器无图标），且 `index.html` 标题仍是 `Vite App`，这两处随本项一并改掉（2026-09-11 完成：`components/AppBackground.vue` 三层渐变 + 粒子用纯 CSS/内联 SVG 兜底、`RoomInfoCard` 模组封面渐变占位、`index.html` 标题「雾都疑云 · CoC 跑团助手」+ `lang="zh-CN"` + 内联 SVG favicon）
- [x] **④ 系统设置页**（新增模块，原项目没有；用户要求：设置里要能自选背景图）：`/settings` 三块——外观（背景预设 + 本机上传自选图 / 氛围强度 / 动效 / 发光 / 字号档）、音效（WebAudio 合成提示音总开关）、AI 配置（收编原大厅的 LLM 详细设置）；本机项存 localStorage 即时生效（2026-09-11 完成：`views/SettingsView.vue` + `components/SettingsPanel.vue` + `stores/settings.ts` + `composables/useBackgroundImage.ts` + `utils/sfx.ts`，浏览器实测背景预设切换/字号 1.15/持久化均生效）
- [x] **⑤ 消息流视觉统一**（`components/chat/*`）：AI 叙事/玩家行动/系统/骰子徽章/仅KP 紫行/四段叙事「行动切口」按钮统一为暗色气泡与卡片体系；KP 与 AI 叙事带头像行（对齐样例的 `头像 + 昵称 + 时间` 结构）；「重要信息」高亮卡（对齐样例的琥珀色提示卡）落到状态变更行上；新消息淡入动效（历史回放不重播）（2026-09-11 完成：新增 `components/chat/{ChatMessageItem,ChatAvatar,ChatNoticeCard}.vue`，`ChatStream.vue` 收敛为容器；玩家端 + KP 端浏览器实测九类分支全部命中）
- [x] **⑥ KP 控制台重排**（改动最大，37KB 巨型视图借机拆子组件）：中央剧情流为主角（模组标题+序章横幅置顶）；左侧角色列表卡片化（头像/职业/在线徽章/HP·SAN 条）；右侧工具区收纳为「检定与投点 / 状态总览(理智) / 聊天频道」分组面板，现有 AI 建议/检定下放/模组骨架/KP 风格/存档面板分组折叠进去
- [x] **⑦ 玩家房间页重排**：剧情流为主 + 模组横幅；我的角色卡侧栏卡片化（HP/SAN 进度条样式对齐样例）；检定面板对齐样例右栏
- [x] **⑧ 大厅页重排**：首屏信息层级（创建/加入为主操作，模组库/API 配置次级入口）
- [x] **⑨ 三态统一与骨架屏**（原 6.2 项保留）：统一空态/加载态/错误态三件套组件 + 加载骨架屏（现在只有 el-empty 与 spinner）
- [x] **⑩ 移动端适配**（原 6.2 项保留，优先级最后、时间不够可裁）：房间页单列布局、侧栏改抽屉、骰子与发送按钮加大
- [ ] **验收**：三主界面（大厅/房间/KP 台）对照样例图走查通过；切主题只改令牌文件一处生效；vue-tsc 通过 + 既有 GUI 流程回归不破（模式切换/检定下放/建议采纳全链路）

#### 6.3 健壮性与错误治理（0.5 天）
- [ ] 统一错误提示与**重试入口**（LLM 降级横幅已有，补 KP 侧「重试本轮」按钮）
- [ ] 表单校验收口（技能上限已随反馈 #6 落地；补属性/物品/背景的边界与必填提示）。**6.1 实测遗留**：建卡第三步「任意特长」流程不直观——`free_picks>0` 的职业（如医生 2 个）必须先用「自由添加技能（兴趣点）」加行、再把该行勾成本职，而界面上所有本职开关初始都是 disabled，用户只看到红字「任意特长需标记 2 个」不知道该做什么；应给出可点击的引导（直接列出可标记的自定义技能行 / 提示先添加技能）
- [ ] 后端统一异常 JSON 形态 + 未捕获异常兜底（现在依赖 FastAPI 默认 detail）
- [ ] 前端断网/后端挂掉的可感知提示（WS 重连中/已断开状态条）
- [ ] **接线 `validate_group_selection`**（`occupation.py` 定义已久、服务端未用，组选择目前只靠前端拦）
- [ ] **WS 频道白名单**（`ws/rooms.py` 的 TODO）：narrative 频道目前全员可发，玩家能伪造 KP 署名叙事——按 role 校验或改白名单

#### 6.4 性能与容量（0.5 天）
- [ ] 实测口径落地：单房 6 连接 + 并发掷骰 + AI 轮次在跑 → 广播 P95 延迟 < 200ms、聊天输入不阻塞
- [ ] SQLite：开 WAL + 写锁热点审视（AI 轮次与玩家操作并发时）
- [ ] 长团体验：消息列表虚拟滚动 / 分页（千条以上不卡）
- [ ] LLM 侧：按房间 token 面板（已落地）复盘一轮成本，必要时再降编排开销（模组按幕裁剪、工具定义瘦身等，见 §6.1 待办）

#### 6.5 安全与隐私收口（0.5 天；进内网/公网前必做）
- [ ] 全局资源鉴权：模组 CRUD、KP 风格 CRUD 目前任何访客可调（局域网 MVP 的取舍，上线前收紧）
- [ ] CORS 收紧为可配置白名单（现写死 127.0.0.1:5173）
- [ ] 房间号暴力枚举防护（8 位短码 + 失败限速）
- [ ] 日志脱敏：key / 玩家昵称 / 聊天正文不入日志（现仅记元数据，复核一遍）
- [ ] 确认前端永不回显 key 明文（现状 ✅，验收时复测）

#### 6.6 演示与验收（0.5 天）
- [ ] 一键自检脚本：pytest + vue-tsc + `/api/health` + 一条 mock 全流程冒烟
- [ ] 3 分钟演示脚本（分镜）：建房 → 玩家入房带卡 → 双聊天框 → 明骰/暗骰 → 模组上传解析 → 挂载 → 协同建议 → 切全自动跑一轮 → 检卡 → 存读档 → 退出
- [ ] 演示素材：功能截图集 / 关键界面录屏
- [ ] **验收**：全新电脑按《部署文档》10 分钟内跑起来；按《使用说明》完成一局演示团（含一次断网降级恢复）

#### 阶段 6 明确不做（保持范围）
- 多人跨幕换卡（《雪盲》类单人模组改编）、法术/魔法书系统、战役长线成长（幕间成长）、移动端原生封装

---

---

## 8. 目录结构规划

```
COC_project/
├── goal.md                  # 本文件（总控）
├── start.bat                # 6.1 一键启动（纯 ASCII 引导壳，勿加中文/chcp）
├── scripts/
│   └── bootstrap.py         # 6.1 一键启动驱动（环境检测/依赖/建库/构建/起服务）
├── other/                   # 原始资料（计划书/规则书/角色卡），不修改
├── docs/                    # 项目文档（规则笔记、API 契约、部署文档、使用说明）
└── project/
    ├── frontend/            # Vue3 + Vite + TS（dist 产物由后端单端口托管）
    │   └── src/
    │       ├── api/         # REST 与 WS 客户端封装
    │       ├── stores/      # Pinia：room / chat / card / game
    │       ├── views/       # 页面：Home / Room / CardEdit / CardDetail / KPConsole / Modules
    │       ├── components/  # 骰子动画 / 聊天框 / 角色卡分区组件
    │       └── types/       # 消息协议与角色卡 TS 类型
    └── backend/
        ├── app/
        │   ├── main.py      # FastAPI 入口 + 静态托管 + WS 路由
        │   ├── static_hosting.py  # 6.1 单端口托管（SPA fallback，D6）
        │   ├── api/         # REST 路由：rooms / cards / saves / modules
        │   ├── ws/          # WebSocket 连接管理与广播
        │   ├── rules/       # CoC7 规则引擎（纯函数）
        │   ├── llm/         # 供应商适配层 + function calling 工具集（§6.7）
        │   ├── agent/       # Agent 核心（§6）：提示词组装 / KP 风格 / 剧情记忆 / 可见性过滤
        │   │   ├── prompts/       # L1 基座提示词模板（版本化，§6.1/6.3）
        │   │   └── kp_styles/     # KP 风格 JSON（沉浸/教学/平衡 + 自定义，§6.2）
        │   ├── models/      # SQLModel 表定义（含 §6.5 剧情记忆五要素表）
        │   └── seed/        # 职业/技能种子数据 JSON
        └── tests/           # pytest：规则引擎 + API
```

---

## 9. 关键技术决策记录

| # | 决策 | 理由 | 可撤销条件 |
| --- | --- | --- | --- |
| D1 | 前端 React → **Vue3**（修正计划书） | 用户明确指定 | 无 |
| D2 | LLM 统一走 OpenAI 兼容协议 | GLM/DeepSeek/OpenAI 三家同构，适配层只写一次 | 出现不兼容供应商需求时再扩展独立适配器 |
| D3 | LLM 状态变更仅通过 function calling | 保证骰子与数值由规则引擎裁定，防 LLM 幻觉改数值 | 无（原则性决策） |
| D4 | 局域网发现 MVP 用 IP+链接，UDP 广播后置 | 降低首版复杂度，手动输入不影响核心流程 | 阶段 6 打磨时若时间充裕补 UDP 发现 |
| D5 | 检定计算放后端规则引擎 | 服务端权威 + 便于单测 + LLM 复用 | 无 |
| D6 | 单端口部署（FastAPI 托管前端静态文件） | 局域网使用门槛最低 | 无 |
| D7 | Agent 提示词分层组装 + KP 风格实现为 JSON 配置 | 风格可切换可自定义，提示词可版本化回归测试（借鉴 model_skills/coc-trpg-skill） | 出现更优编排方案时重构组装器 |
| D8 | 信息双可见性 public/keeper 全链路贯穿（记忆、消息、线索、暗骰），输出经强制过滤 | 防超游与防 AI 剧透是系统级保障，不依赖提示词自觉（借鉴 trpg-log-copilot） | 无（原则性决策） |
| D9 | LLM 数值变更仅能通过工具且必须携带 reason | 全部状态可溯源、可回放，防幻觉改数值 | 无（原则性决策） |
| D10 | 阶段 4 拆分 4.1~4.4：协同模式先行（4.1）、记忆五要素后置（4.3）、llm_config 先用 .env（4.4 才入库） | 每小阶段可独立验收；协同模式 LLM 无写权、无需可见性过滤，风险最低且先验证提示词质量；短团没有持久线索也能玩 | 阶段 4 全部完成后自然失效 |
| D11 | LLM 供应商接入 = 单一 OpenAI 兼容客户端 + 供应商注册表（仅 label/base_url）+ `GET /llm/models` 实时探测 + 手填兜底；key 形态自动识别降级为展示参考、不进关键路径 | 模型名迭代太快静态表必过期（实证：GLM-4.7-Flash 免费档取代 glm-4-flash；DeepSeek 2026-07-24 下线旧名）；AiChatTrpg/workbench 均采用探测方案，workbench 自建模型目录库后撤掉是教训 | 无（接入层稳定性依赖） |

---

## 10. 风险与对策（继承计划书 + 新增）

| 风险 | 对策 |
| --- | --- |
| LLM API 延迟/失败 | 30s 超时 + 重试 2 次 → 降级纯人工主持；LLM 等待不阻塞聊天与其他操作 |
| LLM 记忆断裂（长团） | 滚动窗口 + 摘要压缩 + 模组结构化 JSON 作为长期记忆锚点 |
| Token 成本 | 日常用 GLM-Flash 级模型，检定走本地引擎，上下文摘要压缩 |
| WS 不稳定 | 心跳 + 自动重连 + seq 序号 + 重连全量同步 |
| 多端写入冲突 | 服务端权威裁定，KP 最终决策 |
| 规则实现遗漏/错误 | 以规则书 PDF 为准逐条核对公式，规则引擎全覆盖单测 |
| **角色卡 xlsx 过于复杂导致照抄不可行** | 只提取数据结构做参考，界面按 MVP 精简（技能/背景/战斗三区），不必复刻全部 12 个 sheet 的功能 |
| LLM 越权：剧透真相 / 编造规则 / 绕过骰子直接改数值 | 可见性强制过滤（§6.4）+ 一切变更走工具（§6.7）+ L1 基座硬约束 + 协同模式 KP 可一键回滚 AI 输出 |
| 长团后风格漂移、剧情遗忘 | 滚动摘要 + 每轮重注入 L1/L2 层 + 剧情记忆五要素锚点（§6.5） |
| 模组解析结构化失败 | 分章节抽取 + schema 校验失败重试 + 保留原文允许 KP 手动补结构 |

---

## 11. 变更记录

| 日期 | 变更 | 备注 |
| --- | --- | --- |
| 2026-09-03 | 初版：基于计划书制定，前端选型修正为 Vue3，形成 7 阶段可勾选任务清单 | 资料来源：other/ 三份文档 |
| 2026-09-03 | 新增 §6「Agent 配置设计」：提示词分层 / KP 风格 / 四段输出协议 / 可见性防超游 / 剧情记忆五要素 / NPC 模板 / 工具集铁律 / 模组 schema / 提示词规范；阶段 4 扩充为 5 天并逐项引用 §6 | 资料来源：model_skills/ 四个开源 skill 借鉴 + 自行补充 |
| 2026-09-06 | 阶段 4 拆分为 4.1~4.4（协同先行 / 记忆五要素后置 / llm_config 先 .env，决策 D10）；规则库理智/疯狂表前移至 4.2；阶段 6 瘦身（存读档/历史检索/心跳重连已随 3.4 完成）；§0 下一步动作改为阶段 4.1，并记录 2.5 剩余 4 项的穿插做法 | 依据：3.1~3.4 已提前落地 D8/D9 基础设施，阶段 4 工具层多为薄包装 |
| 2026-09-06 | 三用户30轮 GUI 验收测试后集中修复：组技能幂等（checkbox-group 全量回调重复 push 已选项）；KP 控制台守卫改"先验证后建连"+ WS 旧连接回调实例守卫（消弹回竞态的僵尸连接/重复消息）；解散房间先广播 room_dissolved 再关全房连接（玩家不再滞留幽灵房）；新增 PUT /rooms/{id}/start 开团流转（waiting→playing，控制台「开团」面板）+ 首套 API 测试 tests/test_rooms_api.py（20 用例全绿）；进房提示排除本人广播+前端系统行尾去重（消双份）；eraLabel 上移 types 共用；新增房间离开确认守卫 | 来源：30轮真人流程 GUI 测试（4 bug + 3 体验问题） |
| 2026-09-06 | **阶段 4.1 完成**：新增 `app/llm/`（config/providers/provider：openai SDK + 供应商预设与 key 识别 + 30s 超时/2 重试/LLMUnavailableError 分类降级）与 `app/agent/`（prompts/l1_base 版本化 L1 + assembler 最小组装器 L1+L5 预留 L2/L3/L4 + suggest 协同建议引擎：单飞合并/连续 3 失败自动回退）；REST 增 PUT agent-mode、POST suggestions/generate、GET llm/status、POST llm/test；Room 加 agent_mode 列（删库重建）；WS chat_send 挂玩家行动自动触发；前端新增 AiSuggestionPanel（模式开关/建议卡片/采纳/编辑/重生成/降级横幅）挂 KP 工具箱；.env/.env.example（千问实测通过）+.gitignore 排除；测试 37→71 全绿；浏览器双页面验收通过（4 截图）。修复过程顺手解决：面板 agent_mode 回显时序（onMounted→watch roomId）、check_hint stake"失败则"前缀重复 | goal §7 4.1；ccswitch 预设思路落地 providers.py |
| 2026-09-06 | **4.1 代码评审 + 新开源项目经验吸收**：调研 AiChatTrpg-main / trpg-workbench-master 的 LLM 接入实现；结论 4.1 架构方向正确无需重写，新增 §7「4.1+ 修订清单」（模型静态表改实时探测+手填兜底 / key 启发式降级为参考 / 最小 KP 设置面板建议从 4.4 提前 / _collect_context 移 to_thread / deadline 自洽 / create_task 异常回调 / temperature 黑名单 / ping 免重试；可选：自动触发 debounce、response_format json_object、Mock 客户端）；§6.1 增补缓存感知布局（BP1/BP2/BP3 映射 L1~L5）；4.2 增补提案→校验→确认契约与流式可选项；新增决策 D11 | 已联网核实：GLM-4.7-Flash 免费档现役、DeepSeek 旧模型名 2026-07-24 下线 |
| 2026-09-06 | **4.3 后端主体完成（AI 代写）**：新增 clue/thread/clock/npc 四张表 + 六个记忆工具（add_clue/update_clue/add_thread/resolve_thread/advance_clock/upsert_npc）；L3 记忆快照注入 BP2；D8 系统级兜底过滤 filter_final_visibility（keeper 片段从公开叙事强制摘除转 keeper_notes）；场景收束双份摘要（set_scene 触发后台生成，玩家版入 BP2）；测试 150→167 全绿。**新增表 → 需删库重跑 scripts/init_db.py --force**。前置小修确认已随 9543429 完成（keeper debounce / tools 拒绝显式报错 / roll_check 服务端查值 / 骰子表达式规模校验）。协作模式变更：后续代码 AI 主写，用户只做人工测试与提供资料 | 待人工验收：跨场景引用线索/NPC、摘要无剧透 |
| 2026-09-07 | **4.3 十轮双端实测验收通过 + 实测问题修复**：① san_today 跨天清零（回归测试留仓）；② **技能当前值读取 bug**——keeper 上下文与 _skill_value 误读 occupation_points/interest_points，存档格式实为 increment，导致检定按基础值进行（对玩家严重不利，已修 + 验证：心理学 10→80）；③ **检定下放（方案甲落地）**：新工具 request_check——AI 定技能/难度/后果、下放玩家本人投掷（POST /rooms/{id}/check-requests/{req}/roll，服务端按卡查值结算，防自掷刷优势），auto 模式玩家端隐藏自掷面板；④ set_scene 同轮去重（标题未变静默更新）；⑤ 进出房重连去重（超时掉线不广播离开、冷却窗口内静默重连）；⑥ LLM_DISABLE_THINKING（qwen3 系混合推理默认思考致非流式超时，DashScope extra_body enable_thinking=false + 供应商拒绝时降参）；⑦ LLM_TIMEOUT 150s；⑧ dashscope 预设刷新 qwen3.8-max/qwen3.8-flash（官方文档核实）。实测十轮：qwen3.8-max 叙事质量高、伏笔持续回收、无剧透泄漏；测试 167 全绿 | 遗留至 4.4：AI 偶发绕过 request_check 直接 roll_check 代掷（需工具层拦截）；降级后 keeperPending 小 UI 残留；模型延迟波动大→分级路由更必要 |
| 2026-09-06 | **4.1 用户试玩反馈修复 + 《八月二十二日》模组 10 轮实测**：①真凶——latest_action 遍历方向写反（取到窗口最旧玩家消息，建议永远回应第一轮行动），改为"窗口最新一条消息（不分 KP/玩家）"+ 回归测试；②自动触发扩展到 KP 叙事（单人跑团也刷新）+ 采纳即从面板移除 + 批次显示时间戳；③user 消息结尾强约束"建议必须紧接最新剧情推进"（消上下文滞后）；④L1 加恐怖克制与模组贴合约束；⑤LLM 输出 JSON 解析失败自动带原输出重问一次修复 + 预剥尾逗号；⑥L3 模组骨架注入：`backend/data/scenario_brief.txt`（4.1 临时方案，阶段 5 替换为模组库），已注入《八月二十二日》跑通 10 轮（导入/传单/游乐园/药袋侦查/家庭餐厅/循环惊醒/理智检定扣 SAN/莲荷町老人，建议均含模组元素）；⑦清掉直插库的无技能残卡（玩家掷骰按钮永久禁用的根因），SkillCheckPanel 自动选中首技能 + 禁用原因提示；⑧测试 71→73 全绿；截图 41-5 | 用户试玩 4 条反馈全部定位并修复 |
| 2026-09-06 | **4.1+ 修订清单全部完成（含可选三项）**：①预设刷新+实时探测——providers.py 现役模型名（glm-5.3-flash/glm-5.3、deepseek-v4-pro/deepseek-v4-flash、gpt-5-mini/gpt-5.2，官方文档核实）+ provider.list_models() + GET /llm/models + /llm/status 透出 presets，测试锁现役名；②最小 KP 设置面板提前——PUT /llm/config（update_env_file 行级改写 .env + reload_settings 热重载：pop LLM_* 再 override 重读）+ 前端 LlmSettingsDialog.vue（预设 chips/掩码 key/探测下拉 allow-create 手填/脏表单先保存确认）挂 KP 工具箱；③健壮性——_collect_context 移 asyncio.to_thread、_compute_deadline 自洽（3×30+2.4+1≈93.4s）、app/tasks.py spawn_background 异常回调替换 3 处裸 create_task、temperature 黑名单（gpt-5/o1/o3/o4/codex）、ping attempts=1 免重试链；④可选三项——自动触发 2.5s debounce（schedule_auto_generate/cancel_auto）、chat() json_mode（供应商拒绝时同轮次去参重试）、MockLLMClient（LLM_MODEL=mock，断网演示兜底）；测试 73→104 全绿（新增 test_llm_provider.py + llm_config/suggestions_api 扩充）；浏览器双页面验收：设置回显/连通延迟 2922ms/探测 249 模型/改模型保存回显/协同建议采纳双端同步/连发两条仅一批（debounce）/mock 演示建议/改坏 base_url 三连败自动回退 manual+系统消息落库回放/恢复后全链路回归，截图 41-6~41-13 入 gui-test-screenshots/ | goal §7 4.1+；决策 D11 落地 |
| 2026-09-06 | **阶段 4.2 完成：Function Calling + 全自动主持 MVP**：①规则库前移——extract_madness_tables.py 从 docs 抽取疯狂四表（即时/总结 1D10 + 恐惧/躁狂 D100）生成 madness_tables.json，sanity.py 实现损失公式解析/大失败取最大值/三种疯狂判定（临时疯狂 INT 检定成功=发疯的反直觉规则、不定按当日累计 1/5 SAN、永久 SAN=0）+症状表联动；②provider.chat_with_tools（AssistantTurn，复用重试/deadline/temperature/json_mode）+ mock 工具循环脚本化；③工具集 app/agent/tools.py 8 工具（roll_check/roll_dice/secret_roll/san_check/update_status/set_scene/get_card/record_events），state_ops.py 把 kp.py 的 status/scene 主体抽成 REST 与工具共享层；④AutoKeeper（keeper.py）：工具循环 ≤5 轮、终稿修复重问、单飞合并补跑、三连败回退 manual；⑤scenario_state 表（scene/events≤20/san_today）；⑥assembler.build_auto_messages 按 BP1/BP2/BP3 缓存感知布局（骨架+场景前置稳定、事件/技能表/窗口尾部每轮变）+ AUTO_PROTOCOL（l1-v2-auto）+ parse_auto_turn；⑦可见性双通道：narration_public 全员广播、keeper_notes secret 落库+定向 KP（history 收紧为 secret 行一律仅 KP），dice.roll 正则修复大小写（1D6）；⑧前端三档模式（radio-group）/AI 主持蓝 chip/行动切口可点击/自由行动提示/仅 KP 紫行/血条驱动零改动；测试 104→148 全绿（sanity 13 + tools 17 + keeper 9 + 模式档位更新）；浏览器双页面验收：mock 全流程（检定徽章→四段叙事→选项点击→下一轮）+ qwen-flash 真实验收线（san_check 徽章/状态行、暗骰 1D6→5 仅 KP、SAN 59→55 血条实时、set_scene 场景 chip、keeper 笔记含模组递进建议）、玩家端 keeper/暗骰 DOM 断言 0、改坏 base_url 三连败自动回退 manual；截图 42-1~42-6 | goal §7 4.2；§6.3/6.4/6.7 首次全链路落地 |
| 2026-09-06 | **4.2 debug + 4.3 前置小修**：①AutoKeeper 加静默期 debounce（AUTO_DEBOUNCE_SECONDS=2.5，schedule_turn/cancel_scheduled）——auto 模式一轮最多 5 次 LLM 调用是 token 大头，单飞防并发之外补防频率；WS 分流按角色：玩家行动走静默期、KP 插话 run_immediately 取消计时立即开轮；②roll_check 带 target 改服务端查卡取值（D5 完全体）：LLM 报的 value 被忽略，技能表查不到即 error 回喂引导 get_card，schema/AUTO_PROTOCOL 同步；③provider：供应商 400 拒绝 tools 时显式抛 bad_request（提示换模型走降级），不再静默去参跑偏，json_mode 拒绝仍静默去参；④debug 排查顺手修：persist_keeper_note 裸 create_task→spawn_background、run_turn 补 Exception 兜底（计失败+keeper 提示防「主持中」永久挂起）、每次失败给 KP 发 keeper 提示、骰子表达式规模上限（数量≤100/面数≤1000 防幻觉表达式拖死执行）、MadnessResult.summary 中文标签；测试 148→161 全绿；UI 烟雾（真实模型）验证静默期内连发两条仅一轮 | 用户反馈 3 项 + 自查 4 项；期间合并用户 san_today 日期桶改进 | 
| 2026-09-08 | **阶段 4.4 完成（阶段 4 收官，AI 代写）**：①KP 风格系统（§6.2）——kp_styles.py 四旋钮 JSON（内置沉浸/教学/平衡）+ kp_style 表自定义 + render_style_directive 渲染 L2（collab 拼 system / auto 放 BP2），REST kp-styles CRUD + PUT rooms/{id}/kp-style（sys 落库 + kp_style_changed 全员广播），前端 KpStylePanel.vue（下拉分组 + 自定义弹窗四旋钮编辑 + JSON 导入导出）；②llm_config 入库——config.py 重写为 DB 权威（单行 id=1，.env 仅首次 seed），save_settings + PUT /llm/config 扩展 light_* 三字段；③轻量分级路由——LLMSettings.light_ready/with_light_as_main + get_light_client()（suggest 生成/场景摘要走轻任务模型，留空=主模型）；④token 统计——usage.py 全局总账（LlmUsage 单行），provider._complete 记账，/llm/status 透出 + 设置面板展示；⑤遗留修复——roll_check 带 target 工具层硬拦截（schema 移除 target）、keeper 降级同步广播 suggestions 信封（前端清 keeperPending）；⑥provider 实测健壮性——DeepSeek-v4-pro 设 max_tokens 触发异常长思考（reasoning 吃满预算 content 空），改为调用方默认不传 max_tokens（实测不传时 3s/41 tokens 收敛）+ 翻倍重试兜底 + ping max_tokens 64；⑦存量迁移 scripts/migrate_44.py；测试 167→180 全绿（新增 test_kp_styles.py + 重写 test_llm_config.py/test_suggestions_api 配置段）；浏览器双端实测：风格切换广播/叙事差异肉眼可见（沉浸多感官 vs 教学讲规则依据）、协同建议轻任务路由（model=qwen3.8-flash）、全自动完整验收线（探索→3 次检定下放→暗骰→san_check 扣 SAN 27→26→线索-01~06→时钟 4/4 走满看守现身）全程玩家端零剧透、三连败自动降级、Token 总账 52 次/460k in/69k out | 决策变更（用户 2026-09-08）：llm_config=DB 权威 .env 做 seed；分级路由=轻量两档；token 统计=仅全局累计；测试用真实模型，因 DeepSeek pro 消耗过高（几轮 3 元）实测中途全量切千问（主 qwen3.8-max + 轻 qwen3.8-flash） |
| 2026-09-08 | **人工测试四项反馈修复（AI 代写，浏览器双端实测通过）**：①collab 模式 KP 手动检定下放——tools.py 抽 create_check_request 公共函数（AI request_check 与 KP 手动共用）+ 新端点 POST /rooms/{id}/check-requests（kp.py，kp_name 鉴权）+ KPConsoleView「检定下放」面板（目标/技能/难度/缘由，sender 为 KP）；②LLM 运行时参数打通——PUT /llm/config 与设置面板补 timeout/retries/disable_thinking（修复 DB 权威后 30s 超时无法自救的配置悬空），实测 timeout=600 + qwen3.8-max 主/qwen3.8-flash 轻全链路建议生成成功；/llm/test 一并 ping 轻模型（light_latency_ms/light_error）；AiSuggestionPanel 增加「已思考 Ns」实时计时；③离开判定重构——WS 断开一律按掉线（不落库/不广播/不改成员列表），显式 leave 才算退出（退出按钮发 WS leave；关网页 pagehide→sendBeacon POST /rooms/{id}/leave 删花名册行+广播），成员列表/room_state 改用持久花名册全量，prune_stale_loop 改静默摘除+补 ws.close()（180s），前端心跳 PONG_TIMEOUT=90s+document.hidden 跳过判死+visibilitychange 补 ping；enterRoom 幂等调 REST joinRoom 补花名册行（beacon 删行后刷新自愈），join 对 KP 行缺失也补建；④死代码清理——删脚手架遗留 12 文件（TheWelcome/WelcomeItem/HelloWorld/icons×5/assets css×2+logo.svg/HelloWorld.spec/App.spec/e2e vue.spec），补生成缺失的 app/rules/data/madness_tables.json（extract_madness_tables.py，276 行），AboutView 占位页补实内容；pytest 180 全绿 + vue-tsc 通过 | 遗留记录：Card.owner 占位、narrative 频道全员可发（TODO）、validate_group_selection 未接线（有意为之）、L4 card_detail 恒 None（阶段 5 接模组库） |
| 2026-09-10 | **模组临时接入点恢复**：重建 scenario_brief.example.txt（格式模板+使用说明：骨架 1000~2000 字、全局单文件、改动即生效无需重启）；依用户提供的《雪盲》（Sabrina 著，docx 于 COC_project/docs/测试模组/，人工资料不进本仓库）手写生成 backend/data/scenario_brief.txt（1776 字骨架：背景/核心异常/三幕剧情链/时钟/NPC/检定/三条线索路径/挽歌基调），已验证 _load_scenario_brief() 可加载——协同建议与全自动主持的 L3 层即接入该骨架 | 阶段 5 前的临时方案（4.1 遗留）：全局单文件、所有房间共享；模组库上线后按房间选择替换 |
| 2026-09-10 | **阶段 5 完成（AI 代写）**：① **模组库数据层**——新建 `module_scenario` 表（raw_text 全文 / parsed 结构化 JSON / parse_status 状态机 / parse_model 追溯）+ `Room.module_id`，增量迁移 `scripts/migrate_45.py`（幂等，不动存量房间与存档）；② **上传与提取**——`app/api/modules.py`（列表/上传/详情/局部覆盖校对/删除）与 `app/agent/module_parser.py` 提取器：TXT/MD 编码链回退、DOCX 用标准库 zipfile 读 word/document.xml（venv 无 python-docx）、PDF 用 pypdf，含体积/空文本/扫描件错误分支；③ **结构化解析**——分块（≤4000 字、200 字重叠，≤3 块单次抽取，超则总览+逐块）→ map/reduce 合并（实体名归一 _canon_key 剥后缀与括号、技能同义归一 canon_skill、时长字段取长、acts 以总览为准、线索/检定去重合并、条目上限+截断警告）→ normalize_parsed 唯一形态；解析走 `spawn_background` + 轮询，进程内 `_PARSING` 集合做幂等与重启自愈，JSON 解析失败带原文重问一次；④ **手动解析 + 选模型**——`POST /modules/{id}/parse`（可传 model，留空=轻任务模型），上传不自动解析；⑤ **模组库前端**——`/modules` 列表（卡片网格/状态徽章）、`/modules/:id` 详情（解析面板+原文检索高亮+结构化分块就地编辑）、上传弹窗，均独立组件（不塞进 1100 行的 KPConsoleView）；⑥ **房间挂载与注入替换**——`PUT /rooms/{id}/module`（kp_name 403 + sys 消息 + module_changed 全员广播）+ `app/agent/module_context.py` 的 `load_module_brief` 同时接管协同 L3 与全自动 BP2（未挂载回退 scenario_brief.txt），渲染分【公开层】【仅KP】两层并按字段裁剪；模组守秘字段并入 `_keeper_markers`（补上"刚挂模组、线索还没登记"的防剧透盲区）；⑦ 测试 189→266 全绿（新增 test_module_extract/parser/modules_api/binding 四个文件）+ vue-tsc 通过；真实模型实测：《雪盲》DOCX 单次解析 42s（3 幕/5 NPC/6 线索/2 时钟/3 结局/4 检定，含 4 条存疑提示）、《八月二十二日》PDF 多块解析 193s（修合并前是 8 幕/7 时钟/17 结局/22 检定，修后 4 幕/2 时钟/4 结局/15 检定） | 用户决策：结构化结果可人工校对、一房一模组、手动选模型解析；浏览器实测见下一行 |
| 2026-09-10 | **用户 7 条实测反馈修复 + 阶段 6 重写（AI 代写）**：① **模组解析门禁**——解析页加「检测模型」（`POST /llm/test`，前端超时放宽到 90s，此前 10s 会误判慢模型不可用）+ 只读回显当前全局配置，检测通过才启用「开始解析」；大厅新增「API / 模型配置」入口复用 LlmSettingsDialog（全局配置的详细设置页放大厅，房间/模组页只做回显）。② **模组库返回房间**——模组库并入「房间工作区」（router `ROOM_SCOPE_ROUTE_NAMES` 含 module-list/detail：进入不再弹"离开房间"确认，`KPConsoleView.onUnmounted` 也不拆连接），模组页带 `from_room` query → 顶栏「返回 KP 控制台 / 返回大厅」，真正离开工作区时由 `useRoomReturn` 收尾拆连接。③ **按房间 token**——新表 `room_usage`（`scripts/migrate_47.py`）+ `usage_room()` ContextVar（引擎层绑定、provider 记账无需感知 room_id），`GET /rooms/{id}/usage`（kp_name 鉴权），设置面板「本场消耗」行（区别于「全局总账」）。④ **检定下放任意技能**——新模块 `rules/skills.py`（`base_expr` 解算：闪避=DEX/2、母语=EDU）+ `tools.resolve_skill_target`（卡上有→卡值；没有→技能表基础值），KP 面板下拉列「卡面技能 + 其余标准技能（基础值）」，payload 增 `base_value` 标记。⑤ **AI 检卡**（只建议不拦截）——`agent/card_review.py`（卡摘要 + `module_context.module_review_digest` 公开层模组设定 → 轻模型 → JSON，玩家名对齐过滤幻觉）+ `POST /rooms/{id}/card-review` + `CardReviewPanel.vue`。⑥ **技能创建上限**——通读规则书第三章全节确认**规则书未载明该上限**（6→7 版转换章节仅提"KP 可规定 75%"），故取 KP 裁定值 `SKILL_MAX_AT_CREATION = 90`（常量可回退 80）；`validate_allocation` 判定只针对"被点数推过上限"，母语=EDU 这类基础值超限不误报；建卡页加「合计」列与超限红字实时拦截。⑦ **阶段 6 重写**为 6 块（部署与分发 / UI 美化与移动端 / 健壮性 / 性能 / 安全收口 / 演示验收，3~4 天），补上 UI 美化与安全项。测试 271→292 全绿（新增 test_skill_cap.py、test_card_review.py 与工具/用量用例）+ vue-tsc 通过 | 用户 7 条反馈逐条闭环；未做项：检卡结果落库、按轮次明细、模组按幕裁剪 |
| 2026-09-10 | **token 编排体检 + 缓存观测/可见性标注修复（AI 代写）**：① **前缀缓存可观测**——`llm_usage` 补 `cached_tokens`（`scripts/migrate_46.py` 增量迁移），`provider._cached_tokens()` 读 `usage.prompt_tokens_details.cached_tokens`，`get_usage()` 附 `cache_hit_rate`，设置面板改显「命中 N（命中率 X%）· 实际计费输入 = 名义 − 命中」（`cached` 落库前按 `prompt` 夹取）。实测（真实 provider 链路 2 次同前缀调用）：`cached_tokens` 0→1024，正好是 1024-token 最小缓存块；另测得 9275-token 真实房间提示词第 2 次命中 9216（99.4%）——即 `prompt_tokens` 只是名义输入。② **secret 可见性标注**——`assembler._session_line()` 统一渲染 L5 窗口行（协同/全自动共用），`secret=True` 打「·仅KP」+ 段头警示；`keeper/suggest._collect_context` 的 `latest_action` 改 `next((m for m in recent if not m.secret), '')`。根因：全自动每轮结尾必落一条 keeper 笔记（secret，与叙事同 channel），旧 `recent[0]` 会把 AI 自己的守秘笔记当成玩家行动喂回（实测 BP3 出现过「卡面无话术，已改用心理学…」）；而窗口混入 secret 且无标注时模型分不清玩家看过没有，D8 的**逐字**替换兜不住改写过的守秘内容。测试 266→271 全绿（新增 cached 夹取、窗口标注 ×2、latest_action 跳过 secret ×2）+ vue-tsc 通过 | 来源：用户追问"27.9 万 input 是否正常 / 能否省 token" → 全量体检（见 §6.1 两条增补）；同批记录待办：模组骨架按幕裁剪、模组与 clue/npc 表去重、TOOL_SCHEMAS 瘦身、MAX_TOOL_ROUNDS 5→3 |
| 2026-09-10 | **阶段 5 浏览器端到端实测（chrome-devtools，AI 代写）**：① **上传**——`/modules` 拖拽弹窗上传 TXT（9950 字提取成功，自动跳详情页）；② **手动解析 + 选模型**——模型下拉实时探测出 52 个可用模型，显式选 `qwen3.8-max` 后点「开始解析」，状态机 pending→parsing（按钮禁用 + 已耗时计时）→ready；解析质量：3 幕（专家/旅人/挚友）、9 NPC、14 线索、3 时钟、3 结局、1 检定 + 8 条存疑提示，全字段与原文一致，`qwen3.8-max` 明显比 flash 更细（NPC 9 vs 5、线索 14 vs 6）；③ **房间挂载**——KP 台「模组骨架」面板换绑（辉质→雪盲），toast + 面板回显 + `module_changed` 广播系统行三处一致，注入链实测已切换（5138 字《雪盲》骨架，无 PDF 模组残留）；④ **协同模式**——建议文本用上了模组解析出的 **谢尔/英格堡、泪湖、金盏花** 三个要素，三条互不重复 + 检定提示，质量优；⑤ **全自动模式**——AI 一轮内发起 `request_check`（心理学·常规）**成功落地**（player 侧出现投掷按钮，P1 修复闭环）、公开叙事用到英格堡/合影/肩上霜，**玩家端零剧透**（检索不到 keeper 片段/兰莫丽芙家旧宅/寒灾时钟/仅KP 字样），keeper 笔记正确只进 KP 屏；⑥ **实测发现并修复**——`ModuleSelectPanel` 首次回显竞态：父视图 `KPConsoleView.onMounted` 是异步的（先 await getRoom 做 KP 守卫），子组件 onMounted 早于它执行时 `room.roomId` 仍为空串，`getRoom('')` 404 → 面板永久停在"未挂载"；改为 watch roomId（immediate，换房自动重载）后回显正常；⑦ 顺带实测到「删除被引用模组 → 自动解绑」：删掉正在挂载的模组后房间回退默认骨架，系统消息「挂载的模组已被删除，剧情骨架回退默认方案」落库 + 广播 | token 累计 64 次调用 / 27.9 万 input / 5.3 万 output；模组库最终留《雪盲》DOCX + 《八月二十二日》PDF 两份，房间 18408065 挂载《雪盲》 |
| 2026-09-10 | **三模式浏览器实测后修复（AI 代写）**：① **工具 target 名不匹配（核心修复）**——真实现场「玩家昵称 ≠ 角色卡名」时，AI 会照抄【在场调查员】里的卡名当 target，request_check/san_check/update_status 全部报「不在房间内」，整轮检定下放落空。修法两层：提示词侧 keeper/suggest 的 investigators 补 `player_name`，assembler 抽出共用 `_investigator_line`（渲染「玩家昵称（职业｜角色名 X）」，BP3 与建议头部写明 target 必须填玩家昵称）；工具侧 `_load_member_card` 昵称查不到时按卡名反查兜底，并**归一成花名册昵称**返回与落库（check_request 的 payload.target 决定前端「谁能点投掷」）。② **存档列表鉴权补齐**——GET /rooms/{id}/saves 原漏 kp_name 校验（玩家可列存档名），改为 query 鉴权 403，前端 listSaves 透传。③ add_clue 的 keeper 回执「。，」标点修复（裁 content 尾标点 + 改「｜来源：」分隔）。测试 180→189 全绿 + vue-tsc 通过；真实模型回归（房间 18408065，玩家甲带卡 test）：全自动一轮 request_check 成功落地（target 归一为「玩家甲」），玩家点投掷 侦查 95→72 常规成功，AI 还自行回收了早前失败时记下的「伏笔#1 待办」 | 来源：三模式（纯人工/协同/全自动）浏览器实测报告；同批记录低危项：刷新页 pagehide→beacon leave 与重连 join 之间有 ~1s 花名册空缺窗口（enterRoom 幂等补行已兜底，仅竞态） |
| 2026-09-11 | **阶段 6.2 UI 美化任务按样例图重写**：用户提供视觉样例 `other/前端样例.png`（克苏鲁暗色主题：暗色氛围背景/发光描边面板/顶部品牌栏+左侧导航侧栏/剧情流为主角/右侧工具分组面板），6.2 重写为 9 小项（①令牌+EP 暗色地基 → ②全局外壳 Layout → ③背景/品牌素材 → ④KP 台重排（借机拆 37KB 巨型视图）→ ⑤房间页 → ⑥大厅 → ⑦消息气泡统一 → ⑧三态骨架屏 → ⑨移动端可裁），工时 1.5 天上调至 3~4 天（阶段 6 总量 3~4 天→4~5 天）；范围铁律：只动观感与布局，不改业务逻辑/消息协议/store/api，功能映射到现有功能 | 成本评估：纯表现层改造，样例图各功能均已存在；预计 85% 观感可达成（EP 暗色+令牌定制），逐像素复刻不做；素材图（背景/封面/头像）可用 AI 生图或渐变兜底 |
| 2026-09-11 | **阶段 6.1 完成：部署与分发（AI 代写）**：① **单端口托管（D6 落地）**——新增 `app/static_hosting.py::mount_spa()`：dist 缺失时静默跳过（开发模式/pytest 不受影响）、幂等挂载、`/assets` 交 StaticFiles、其余路径先找 dist 真实文件再回 `index.html`（SPA 刷新不 404）、`/api` 与 `/ws` 前缀命中未注册路径时仍回 JSON 404 而不被 HTML 吃掉、防目录穿越、index.html 带 `no-cache`（发版即生效）；`main.py` 在所有 router 之后调用。前端**零改动**（axios 用相对 `/api`、WS 用 `location.host`，同源天然成立）。② **一键启动**——`start.bat` + `scripts/bootstrap.py`：端口预检 → Python/Node 版本 → `.venv`（缺 pip 自动 ensurepip 自愈）→ 依赖按 `requirements.txt` 时间戳 stamp 判定（无 stamp 时先 import 探测，**不无脑重装**旧环境）→ `.env` 自动生成 → 建库或跑 44~47 幂等迁移 → 前端构建（失败自动回退 `build-only` 并提醒）→ 起服务 + 默认路由网卡优先打印局域网地址 + 延迟 6s 开浏览器；支持 `start.bat 8080` / `--rebuild` / `--check`（自检模式，演示前预检用）。③ **首次配置向导**——`.env.example` 重写（三条配置路径 / 注明 llm_config 表才是权威 / mock 与运行时参数 / light_* 只能走设置面板）+ 大厅引导条 `LlmFirstRunGuide.vue`（未配 key 时给「启用演示模式」一键写 `model=mock` 与「去配置」两个出口，设置弹窗关闭后自动重新检测）。④ **文档**——新增 `docs/部署文档.md`（环境准备/一键启动/局域网开团/模型配置/手动启动/FAQ/演示前清单）与 `docs/使用说明.md`（KP 视角全面板 + 玩家建卡与桌上操作），README 同步（一键启动置顶、`venv`→`.venv` 修正）。测试 292→305 全绿（新增 `tests/test_static_hosting.py` 12 例）+ vue-tsc 通过；真实验证：`npm run build` 产物单端口实测（`/`、`/room/XXXX/kp` 回构建后 index.html、`/assets/index-*.js` 200 `application/javascript`、未知 `/api/*` JSON 404、`/docs` 正常）、`start.bat` 真实起服务并自动开浏览器、`--check` 五步全过、二次 `--check` 正确跳过依赖安装 | **踩坑记录（勿回退）**：cmd.exe 读取 UTF-8 批处理时，若文件内执行了 `chcp 65001` 而控制台初始码页不是 65001（用户双击 = 新控制台 CP936），会发生**行读取错位**，中文注释行后半截被当命令执行（实测 `'数据库' is not recognized…`），同文件在 CP65001 控制台却完全正常（非确定性）。故 `start.bat` 保持**纯 ASCII 且不调用 chcp**，中文与全部逻辑移入 `scripts/bootstrap.py`（由它用 `SetConsoleOutputCP(65001)` 设置编码）|
| 2026-09-11 | **阶段 6.2① 设计令牌 + 全局主题地基（AI 代写）**：新增 `src/assets/styles/tokens.css`（唯一色值源：深蓝黑三级背景/青蓝主色/品牌橙/语义色/仅KP紫 + 间距·字号·圆角·阴影·层级，含 `--coc-font-scale` `--coc-glow-strength` 两个设置页可调项）、`global.css`（重置+滚动条+排版基线 + Element Plus 暗色变量映射 `--el-* → --coc-*` + 弹窗/抽屉/下拉/折叠/Tabs/进度条/输入框微调 + `.coc-panel/.coc-chip/.coc-glow-hover` 等通用工具类）、`animations.css`（路由过渡/入场/消息/骰子弹跳光晕/面板呼吸/边框流光/`coc-reduce-motion` 降级）；`main.ts` 显式 `html.dark` + 固定引入顺序（EP 基础 → EP 暗色 → 令牌 → 全局 → 动效）；`App.vue` 移除与令牌冲突的裸色值 body 兜底。验证：vue-tsc 通过、`vite build` 成功且令牌进产物、浏览器实测 `html.class=dark`、`--el-color-primary=#0ea5e9`、`body=#0b1220`、LLM 设置弹窗内按钮/标签/输入框全部暗色（截图 `gui-test-screenshots/screenshot-*.png`） | goal §7 6.2① 完成；本机 shell 编码坑：命令行内**不能出现中文**（会被写成非 UTF-8 ps1 导致路径错乱），一律用相对路径；`npm run xxx` 在本机 shell 报「系统找不到指定的路径」，改用 `node node_modules/<pkg>/bin/xxx.js` 直调 |
| 2026-09-11 | **阶段 6.2②③④ 完成（全局外壳 / 背景与品牌 / 系统设置页，AI 代写）+ 6.2 小项重编号**：① **②全局外壳**——新增 `layouts/AppLayout.vue`（背景层→顶栏→左导航+主内容区，主区承载 `coc-route` 路由过渡）、`AppTopBar.vue`（品牌/局域网徽章/主持模式开关/身份与连接点/设置/全屏）、`AppSideNav.vue`（游戏大厅/当前房间/角色管理/模组库/系统设置 + 底部房间信息卡与「结束游戏」，不在房间时「当前房间」禁用）、`RoomInfoCard.vue`（房间号/人数/模式/进行时长/模组封面占位）、`ModeSwitch.vue`（主持模式三档从 `AiSuggestionPanel` 上提到顶栏，原面板改只读防两处开关打架）；`components/common/CocIcon.vue` + `cocIcons.ts`（内联 SVG，零依赖，不引 FontAwesome CDN，防现场断网）；`App.vue` 改为只挂外壳，RoomView/KPConsoleView/HomeView 高度改 `height:100%`（去掉各自 `calc(100vh - 55px)` 的历史减高）。② **③背景与品牌**——`components/AppBackground.vue` 预设用多层 CSS 渐变 + 暗角、可选氛围光斑（默认关）、自选图叠半透明底色保证文字可读（零外部图片，素材缺失不阻塞）；`index.html` 标题改「雾都疑云 · CoC 跑团助手」+ `lang="zh-CN"` + 内联 SVG data-URI favicon（清掉 6.1 遗留的 `/favicon.ico` 回退与 `Vite App` 标题）。③ **④系统设置页（新增模块）**——`/settings` 三块：外观（背景预设 + 本机上传自选图，`composables/useBackgroundImage.ts` 存 IndexedDB（localStorage 放不下二进制）、单图上限 6MB、objectURL 统一回收并按引用计数释放）、音效（`utils/sfx.ts` WebAudio 合成短音总开关，在 `AppLayout` 常驻监听 store 生效）、AI 配置（把原大厅的 `LlmSettingsDialog` 收编为正式入口，只读回显 + 打开详细设置）；`stores/settings.ts` 写 `--coc-font-scale` / `--coc-glow-strength` / `coc-reduce-motion` 到 documentElement 并持久化。④ **6.2 重编号**——插入 ④（设置页）后原 ④~⑨ 顺延为 ⑤~⑩，并把「消息流视觉统一」提为 ⑤（`ChatStream` 为房间页与 KP 台共用组件，先统一气泡再重排两侧布局）。验证：vue-tsc EXIT=0、`vite build` 成功、单端口浏览器实测背景预设切换/字号 1.15 即时生效并刷新持久、设置页三块内容与 LLM 配置回显正常 | goal §7 6.2②③④；本轮遗留待办：⑤ 消息流气泡统一（`components/chat/*` 尚未创建）、⑥ KP 台重排、⑦ 房间页、⑧ 大厅、⑨ 三态骨架屏、⑩ 移动端 |
| 2026-09-11 | **阶段 6.2⑤ 消息流视觉统一（AI 代写）**：① 新增 `components/chat/ChatMessageItem.vue`——单条消息行，九类渲染分支与抽取前逐条对齐（状态变更卡 / 系统行 / keeper 紫行 / 骰子徽章 / 检定请求卡 / AI 四段叙事+行动切口 / 普通气泡），纯展示组件（`msg`/`myName`/`fulfilled`/`rolling` 走 props，事件上抛）；② 新增 `components/chat/ChatAvatar.vue`（KP 橙盾牌 / AI 青星芒 / 玩家灰首字 / keeper 紫 / 骰子行可显式指定 `dice` 图标）与 `components/chat/ChatNoticeCard.vue`（样例同款琥珀色「重要信息」卡）；③ `ChatStream.vue` 收敛为容器（tab / 滚动跟随 / 输入 / 检定下放投掷），逻辑零改动；④ 配色全部走令牌——骰子徽章不再用 `types/ws.ts` 的浅色 `ROLL_BADGE_STYLES` 直接铺底（白底在暗色流里像一块补丁），改用 tokens 的 `--coc-roll-*` 派生色（**协议层表未动**，语义一一对应），入场/光晕改用 animations.css 的 `coc-roll-in(--epic)`，新消息 `coc-msg-in` 淡入（历史回放不重播）；⑤ 自己的消息右对齐 + 气泡尖角（对齐移动端样例），头部保持「昵称 → 徽章 → 时间」阅读顺序。验证：vue-tsc EXIT=0 + `vite build` 成功；浏览器实测——REST 铺「房间/场景变更/状态变更/明骰/暗骰/检定下放」六类 + 真实输入触发 mock AI 主持，玩家端逐行 DOM 核对九类分支全部命中，KP 端额外命中 keeper 紫行与暗骰的 dice 头像（截图 `.codebuddy/tmp-shots/05-*.png`） | goal §7 6.2⑤；走查临时用的「model=mock + 房间 auto 模式」测完已还原 qwen3.8-flash/manual；本机 shell 仍是 PowerShell 包装（`cd /d` 报错但命令照跑，`node node_modules/vite/bin/vite.js build` 可用） |
| 2026-09-11 | **阶段 6.2⑦⑧⑨ 完成（AI 代写）**：⑦⑧⑨ 已落地并浏览器实测 | 新增 `common/{StatBar,StateView,SkeletonBlock}.vue`；重写 RoomView/HomeView/CardListView；ModuleListView 去硬编码色；`animations.css` 加 `coc-shimmer`/`coc-spin` |
| 2026-09-11 | **阶段 6.2⑥ KP 控制台重排（AI 代写）**：① 右栏工具箱从「11 个平铺面板」（原需滚 20 屏）收成 5 个可折叠分组 `el-collapse`（开团与场景 / 检定与投点 / AI 建议与风格 / 模组与检卡 / 设置与状态），默认只展开第一组，`toolGroups` 状态在 `<script setup>`；② 顶栏改「房间号（等宽字）+ 当前模组 chip + 📍场景 chip + 连接/身份/退出」；③ 左栏成员卡与整卡抽屉的 HP·MP·SAN·幸运 全部从 `el-progress` 换成 `common/StatBar.vue`（`memberBars()` 返回 `tone`，旧 `barColor()` 删除），≤30% 预警沿用卡片红框 + StatBar 自动危险色；④ 全组件 hardcoded 色值清零（`#909399`×11 / `#e8eaed` / `#303133` / `#2c3e50` / `#222d3d` / `#1b2431` / `#f5f7fa` / `#f0f2f5` 等全换成 `var(--coc-*)`，读档弹窗与整卡抽屉的「浅色文档风」一并转暗）。验证：vue-tsc EXIT=0 + `vite build` 成功 + 浏览器实测（五个分组标题与内容 DOM 核对一致、点击折叠/展开 `is-active` 正常切换，截图 `.codebuddy/tmp-shots/06-kp*.png`） | 遗留：⑩ 移动端适配未做（窄屏下 KP 台三栏会挤，需抽屉化）；⑥ 未按原计划把面板拆成 `components/kp/*` 子组件，`KPConsoleView.vue` 仍 1290 行 |
| 2026-09-11 | **阶段 6.2⑩ 移动端适配（AI 代写）+ 6.2 全部小项收口**：① 房间页 ≤820px 单列（剧情流在上、工具侧栏折到下方整宽，横幅换行、退出按钮加高到 `--coc-touch-min`）；② KP 台 ≤900px 单列（成员列表 → 剧情流 → 可折叠工具箱），顶部房间条换行、场景 chip 限宽；③ 全局顶栏 ≤700px 只留 logo + 模式开关 + 图标按钮（品牌文案、局域网徽章、身份 chip、玩家端只读模式 chip 隐藏）；④ 侧栏图标条模式（≤1100px）隐藏房间信息卡（原先被挤成一列字）。验证：vue-tsc EXIT=0 + `vite build` 成功 + agent-browser 手机视口（`set viewport 390 844`）实测房间页与 KP 台，截图 `.codebuddy/tmp-shots/10-mobile-*.png`。**至此 6.2 十项全部完成** | 遗留：⑩ 只做断点降级，未做侧栏抽屉化/手势；测试房间 `F9087CB0` 与 `.codebuddy/tmp-shots/` 临时物待清（REST `DELETE /api/rooms/F9087CB0?kp_name=老周`） |
| 2026-09-11 | **阶段 6.1 浏览器端到端实测（agent-browser，AI 代写）**：单端口 `http://127.0.0.1:8000` 下跑完整真人流程 —— ① 大厅加载（构建产物 `/assets/*` 全部 200、`/api/rooms` 200）；② 首次配置引导条：临时清空 key（走公开接口 `PUT /llm/config {api_key:' '}`，测完已按原值还原）→ 引导条出现「启用演示模式 / 去配置」→ 点「启用演示模式」写入 `model=mock` 且引导条收起；③ KP 建房（中文房名/昵称输入正常）→ 房间号 4F2A9124 → KP 控制台 SPA 深链加载；④ 玩家三步建卡（姓名/性别/古典时代/职业医生/投点法/任意特长标记 2/2 → 「林墨 · 医生」创建成功并跳详情页）；⑤ 玩家加入房间（选卡）→ KP 端「调查团（2）」实时出现；⑥ KP 发剧情 → 玩家端实时可见；KP 宣布开团 → 双端系统行；KP 改场景 → 玩家端 📍 场景 chip + 系统行；⑦ 玩家掷「急救 30」→ 双端同步出现骰子徽章（失败）；⑧ **深链刷新**：`GET /room/4F2A9124?...` 重新加载无 404、消息历史与花名册完整补齐；⑨ 大厅「API / 模型配置」回显已存配置（百炼千问 / qwen3.8-flash / token 总账），点「测试连通」返回 **连通正常 · 延迟 9375ms · 轻模型 656ms**。顺带修掉实测暴露的一处设计问题：`--check`/`--rebuild` 原先会被端口预检拦住，现改为这两种用法跳过预检、真正 serve 前再兜底复检 | 遗留观感项已记入 6.2③（favicon + index.html 标题仍是 Vite App）与 6.3（建卡「任意特长」无引导）；实测数据：房间 4F2A9124 / 卡「林墨·医生」/ 旧卡「test·拳击手」仍留库 |
| 2026-09-11 | **用户实测反馈三连修复（AI 代写）**：① **建卡页浅色残留修复**——`.occupation-info` 的 `#f5f7fa` 浅灰底改暗色卡片（`var(--coc-card-2)`+边框）、`.intro/.mode-desc` 改 `--coc-text-muted`、`.group-box`/`.muted`/`.over-cap` 同步令牌化；AboutView 整页浅色转暗；CardDetailView + 12 个组件批量清零 `#909399`/`#c0c4cc` 残留；② **信用评级纳入职业点消耗**（用户需求，规则书第三章 3.3 口径："信用评级初始为 0，可在其任意投入技能点"，P32 示例记者投 41 点本职技能点=信用评级 41，即**最终值全额占用职业点**）：后端 `validate_allocation(..., credit=)` 把 credit 计入职业点占用、`api/cards.py` 传 `payload.credit`、新增 `tests/test_credit_points.py`（3 例：正好花完通过/多 1 点超支并点名"信用评级占用 N 点"/credit 缺省 0 向后兼容），全库 305→**308 全绿**；前端 `creditCost` computed + 第 1 步信用评级旁显「占用职业点 N」+ 说明文案 + 第 3 步「职业点剩余」扣除联动 + 第 2 步末 credit 超预算拦截，浏览器实测 EDU=45→预算 180、剩余 150=180-30 ✓；③ **移动端按 `移动端样例demo.html` 重构**（原实现为 PC 缩放版：侧栏图标条挡聊天、聊天只占半屏）：新增 `AppBottomNav.vue` 底部 5 tab（大厅/房间/角色/模组/设置，≤768px 显示）+ 侧栏 ≤768px 完全隐藏 + 顶栏手机降高/隐藏全屏键/ModeSwitch icon-only + `.app-shell` 改 `100dvh`（移动端地址栏收放不溢出）+ 房间页 ≤820px「剧情流全屏 + 工具右滑抽屉」（`tools-btn`/`tools-mask`/`side-panel` fixed 抽屉化，替代原单列堆叠）。验证：pytest 308 全绿 + vue-tsc EXIT=0 + `vite build` 成功 + chrome-devtools 移动端（375×812）三页实测（首页底部 tab/房间页全屏聊天截图/抽屉滑出截图）+ 桌面回归（底部导航隐藏、双栏 856+320 布局不变） | 遗留：建卡页第 3 步 tag 行在手机上仍偏挤（可选后续）；桌面 `h1` 品牌文案手测正常；KP 台移动端沿用 ≤900px 单列未再改 |
