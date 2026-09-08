"""SQLModel 表定义 — 表结构的唯一真相源。

当前表（§5.1 / §5.2）：
  - card         角色卡整卡 JSON + 关键字段拆列（§5.1）
  - occupation   职业种子数据（阶段 1 验收用）
  - skill        标准技能清单与基础值（阶段 1 验收用）
  - room         房间（阶段 3，id 为 8 位大写短码，好念好输好口播）
  - room_member  房间成员（KP 与玩家同表，role 区分）
  - message      聊天消息（channel: narrative 剧情流 / ooc 闲聊流 / system 系统）
  - save_game    KP 存档（阶段 3.4：成员花名册 + 各卡 card_data + 场景的 JSON 快照）

约定：表结构稳定前不做增量迁移。任何结构变更 = 删 data/coc.db 重跑
scripts/init_db.py（--force 自动删旧库）。阶段 4 结束后再引入 Alembic。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class Card(SQLModel, table=True):
    """调查员角色卡。card_data 是完整 Investigator JSON（权威数据源）。

    冗余列（owner/name/occupation/era/current_hp/current_sanity）是 card_data
    的投影，只用于 WHERE / ORDER BY / 列表页，展示一律以 card_data 为准。
    写入必须走单一入口 save_card()，同时更新 JSON 与投影列，严禁两边各写。
    """

    __tablename__ = "card"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    owner: str = Field(index=True, description='持有者标识')
    name: str = Field(index=True)
    occupation: str = Field(default='')
    era: str = Field(default='modern')  # classical / modern

    # 整卡 JSON：Investigator 模型序列化结果
    card_data: dict = Field(sa_column=Column(JSON, nullable=False))

    # 投影列（从 card_data["state"] 冗余，供 KP 面板排序/筛选）
    current_hp: int = Field(default=0)
    current_sanity: int = Field(default=0)

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


def save_card(card: Card, card_data: dict) -> Card:
    """Card 的单一写入口：整体替换 card_data 并同步投影列（调用方自行 commit）。

    传入的 card_data 应是调用方改好的新 dict（通常 deepcopy 后修改）——本函数
    以重赋引用的方式触发 SQLAlchemy 对 JSON 列的变更检测，严禁把原 dict 原地
    改完再传入（不会被识别为变更）。
    """
    card.card_data = card_data
    card.name = card_data.get('name', card.name)
    card.occupation = card_data.get('occupation', card.occupation)
    card.era = card_data.get('era', card.era)
    state = card_data.get('state', {})
    card.current_hp = int(state.get('current_hp', 0))
    card.current_sanity = int(state.get('current_sanity', 0))
    card.updated_at = datetime.now()
    return card


class OccupationRow(SQLModel, table=True):
    """职业种子数据：结构化字段拆出，其余整份 JSON。

    静态规则数据，随建卡向导 / 规则查询读取。
    """

    __tablename__ = "occupation"

    id: int = Field(primary_key=True, description='xlsx 职业列表序号')
    name: str = Field(index=True)
    era: str | None = Field(default=None)  # classical / modern / None 通用

    # Occupation schema 的完整 dump（point_formula/fixed_skills/groups 等）
    data: dict = Field(sa_column=Column(JSON, nullable=False))


class SkillRow(SQLModel, table=True):
    """标准技能清单（建卡向导的技能表底子）。

    技能是扁平结构且列表页几乎全列展示，因此全拆列（与 occupation 存 data
    不同：职业是深树且列表只显示三列）。写 API 时直接读列返回即可。
    """

    __tablename__ = "skill"

    id: int = Field(primary_key=True, description='技能清单序号（txt 里的 N）')
    name: str = Field(index=True)
    slot: int = Field(default=0, description='分类技能实例序号：技艺①→1')
    detail: str = Field(default='')
    modern_only: bool = Field(default=False)
    pick: int = Field(default=0, description='需要从候选里选几个：1=选一')
    candidates: list[str] = Field(default_factory=list,
                                  sa_column=Column(JSON),
                                  description='分类技能的候选项，如技艺的 [表演, 美术, 摄影, …]')
    base: int | None = Field(default=None)
    base_expr: str = Field(default='', description='表达式基础值，如 DEX/2、EDU')
    description: str = Field(default='', description='技能说明（txt 里 - 行）')


class Room(SQLModel, table=True):
    """房间。id 用 8 位大写短码（uuid4 截断）：局域网场景口头报号/手输都方便。

    status: waiting（等待玩家）/ playing（开团中）。开团流转由 KP 控制台（3.3）改。
    """

    __tablename__ = "room"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8].upper(), primary_key=True)
    name: str = Field(index=True)
    kp_name: str
    status: str = Field(default='waiting')  # waiting / playing
    # 场景标题栏（阶段 3.3）：KP 可编辑、全员可见，同时是阶段 4 Agent 的场景上下文
    scene_title: str = Field(default='')
    scene_desc: str = Field(default='')
    # Agent 模式（阶段 4.1，决策 D10）：manual 纯人工 / collab 协同建议（4.2 加 auto）
    agent_mode: str = Field(default='manual')
    # KP 风格（阶段 4.4，§6.2）：内置 id（balanced/immersive/teaching）或 kp_style 表的自定义 id
    style_id: str = Field(default='balanced')
    created_at: datetime = Field(default_factory=datetime.now)


class RoomMember(SQLModel, table=True):
    """房间成员。KP 与玩家同表，role 区分；card_id 可空（KP 或暂未绑卡的玩家）。

    重名校验在 API 层按 (room_id, player_name) 做，不加唯一约束——
    成员离房后的重进/改名历史在阶段 3.4 断线重连时再定策略。
    """

    __tablename__ = "room_member"

    id: int | None = Field(default=None, primary_key=True)
    room_id: str = Field(foreign_key='room.id', index=True)
    player_name: str = Field(index=True)
    role: str = Field(default='player')  # kp / player
    card_id: str | None = Field(default=None, foreign_key='card.id')
    joined_at: datetime = Field(default_factory=datetime.now)


class Message(SQLModel, table=True):
    """聊天消息落库。channel 与 WS 信封（§5.3）一致：
    narrative 剧情流 / ooc 闲聊流 / system 系统提示（进出房、阶段 3.2 后含骰子）。
    type 是同一频道内的消息形态标记（§5.2：文本|骰子|系统），骰子消息 type='dice'，
    content 存可读文本。历史检索/断线补齐（3.4）按 room_id 查本表。

    3.4 加两列让历史行自包含（前端按 type 还原 ChatItem 不靠猜）：
      - secret  暗骰标记（D8 延伸）：type=dice 且 secret 的行，history 接口
                只对 viewer==kp_name 返回
      - payload 结构化原始数据（骰子 roll_result / 状态 status_changed 等），
        前端重建骰子徽章与状态行直接用；普通文本行存 {'role': role}
    """

    __tablename__ = "message"

    id: int | None = Field(default=None, primary_key=True)
    room_id: str = Field(foreign_key='room.id', index=True)
    channel: str  # narrative / ooc / system
    type: str = Field(default='text')  # text 文本 / dice 骰子 / sys 系统 / status 状态变更
    sender: str
    content: str
    secret: bool = Field(default=False)
    payload: dict | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.now)


class SaveGame(SQLModel, table=True):
    """KP 存档（阶段 3.4，§5.2 早规划）。snapshot 是恢复时点的全量 JSON 快照：

      {"members": [{player_name, role, card_id}],   # 花名册
       "cards":   {card_id: 整卡 card_data},         # 恢复用 deepcopy 写回
       "scene":   {scene_title, scene_desc}}

    读档 = 快照原子写回 room_member + card_data + scene（复用 save_card），
    聊天历史不在快照里（消息流是时间线，不随读档回滚）。
    """

    __tablename__ = "save_game"

    id: int | None = Field(default=None, primary_key=True)
    room_id: str = Field(foreign_key='room.id', index=True)
    name: str
    snapshot: dict = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=datetime.now)


class ScenarioState(SQLModel, table=True):
    """剧情状态快照（4.2，goal §7：scenario_state 先顶住剧情上下文）。

    data 结构（一房一行，工具层与组装器共用）：
      {"scene":      {scene_title, scene_desc},          # 与 Room 列同源，set_scene 时双写
       "events":     ["关键事件…"],                       # record_events 滚动登记，≤20 条
       "san_today":  {player_name: 当日累计 SAN 损失}}    # san_check 累加，不定性疯狂判定用

    clue / thread / clock / npc 四要素后置 4.3（决策 D10）。
    """

    __tablename__ = "scenario_state"

    room_id: str = Field(primary_key=True, foreign_key='room.id')
    data: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=datetime.now)


# ==================== 剧情记忆五要素（4.3，goal §5.2 / §6.5 / §6.6） ====================
# 五要素 = 场景（scenario_state.data['scene']）+ 实体（角色卡/NPC）+ 线索 + 伏笔 + 时钟。
# 可见性（D8）贯穿：每行带 visibility 字段，LLM 输出经 keeper.py 的过滤兜底。

class Clue(SQLModel, table=True):
    """线索：编号自动分配，验证状态 pending→confirmed / excluded（§6.5）。"""

    __tablename__ = "clue"

    id: int | None = Field(default=None, primary_key=True)
    room_id: str = Field(foreign_key='room.id', index=True)
    code: str = Field(index=True, description='线索编号，如 线索-01（add_clue 按房间序分配）')
    content: str
    source: str = Field(default='', description='来源（谁/哪里获得）')
    points_to: str = Field(default='', description='指向（暗示什么）')
    status: str = Field(default='pending', index=True)  # pending / confirmed / excluded
    visibility: str = Field(default='keeper')  # public 玩家可知 / keeper 仅 KP
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class Thread(SQLModel, table=True):
    """伏笔 / 未结算事项（延迟 SAN、暗骰后果、待回收伏笔），keeper 为主（§6.5）。"""

    __tablename__ = "thread"

    id: int | None = Field(default=None, primary_key=True)
    room_id: str = Field(foreign_key='room.id', index=True)
    content: str
    resolved: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=datetime.now)


class GameClock(SQLModel, table=True):
    """威胁时钟（如「教团仪式 3/4」），进度走满提示 KP；可见性可配置（§6.5）。"""

    __tablename__ = "clock"

    id: int | None = Field(default=None, primary_key=True)
    room_id: str = Field(foreign_key='room.id', index=True)
    name: str = Field(index=True)
    progress: int = Field(default=0, ge=0)
    target: int = Field(default=4, ge=2, le=20)
    visibility: str = Field(default='keeper')  # public / keeper
    note: str = Field(default='', description='走满后的后果备注')
    updated_at: datetime = Field(default_factory=datetime.now)


class Npc(SQLModel, table=True):
    """NPC 实体：核心 NPC 六要素（§6.6）。hidden_motive 为 keeper 专属，
    随剧情更新；status=gone 表示已离场/死亡（exit_plan 是替代方案）。"""

    __tablename__ = "npc"

    id: int | None = Field(default=None, primary_key=True)
    room_id: str = Field(foreign_key='room.id', index=True)
    name: str = Field(index=True)
    status: str = Field(default='active')  # active / gone
    public_identity: str = Field(default='', description='公开身份')
    hidden_motive: str = Field(default='', description='隐藏动机（keeper）')
    player_clues: str = Field(default='', description='玩家可得的线索')
    misdirection: str = Field(default='', description='误导点')
    pressed_reaction: str = Field(default='', description='被逼问时的反应')
    exit_plan: str = Field(default='', description='死亡或离场替代方案（防剧情脆断）')
    updated_at: datetime = Field(default_factory=datetime.now)


# ==================== 阶段 4.4：KP 风格 / llm_config 入库 / Token 统计 ====================

class KpStyle(SQLModel, table=True):
    """自定义 KP 风格（§6.2：内置三种在 app/agent/kp_styles.py，本表只存自定义）。

    params 是四旋钮 JSON：{narrative_density, rule_explanation,
    hidden_roll_transparency, option_granularity}（high/medium/low）+ note 自由补充。
    导出/导入 JSON 即本行序列化。房间引用的 style_id 被删除时自动回退 balanced。
    """

    __tablename__ = 'kp_style'

    id: str = Field(primary_key=True, description='custom-<8位hex>')
    name: str = Field(index=True)
    params: dict = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=datetime.now)


class LlmConfig(SQLModel, table=True):
    """LLM 供应商配置（4.4，决策 D10 收尾：llm_config 入库，单行 id=1 权威）。

    首次启动无行时从 backend/.env 的 LLM_* 读入做种子（.env 保留兼容，
    此后不再是运行时来源）。light_* 是轻任务分级路由（建议生成/场景摘要等
    低风险调用用快模型），light_model 为空 = 跟随主模型。
    """

    __tablename__ = 'llm_config'

    id: int = Field(default=1, primary_key=True)
    base_url: str = Field(default='')
    api_key: str = Field(default='', description='仅存本地 SQLite，接口永不回传明文')
    model: str = Field(default='')
    light_base_url: str = Field(default='', description='轻任务 base_url，空=跟随主模型')
    light_api_key: str = Field(default='', description='轻任务 key，空=跟随主模型')
    light_model: str = Field(default='', description='轻任务模型（建议/摘要等），空=用主模型')
    timeout: float = Field(default=30.0)
    retries: int = Field(default=2)
    disable_thinking: bool = Field(default=False, description='qwen3 系混合推理关思考')
    updated_at: datetime = Field(default_factory=datetime.now)


class LlmUsage(SQLModel, table=True):
    """Token 消耗全局总账（4.4，单行 id=1）：每次真实 LLM 调用后累加。

    粒度为全局累计（用户决策 2026-09-08），mock 调用不计入。
    """

    __tablename__ = 'llm_usage'

    id: int = Field(default=1, primary_key=True)
    calls: int = Field(default=0)
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    updated_at: datetime = Field(default_factory=datetime.now)

