"""Mock LLM 客户端 — 4.1+ 可选项（无 key 跑通全流程 UI / 比赛断网兜底）。

LLM_MODEL=mock 即启用（settings.mock_mode）：get_client() 返回本客户端，
不发任何真实网络请求。chat() 从组装好的提示词里截取【最新剧情推进】内容，
生成 2 条符合 L1 输出协议的合法建议 JSON，保证 parse_suggestions 可解析、
前端可渲染、采纳链路可走通。

4.2：chat_with_tools 按消息状态脚本化——末条消息是工具结果时返回四段
JSON 终稿，否则返回一次 roll_check 工具调用，让全自动主持全流程在
mock 模式下也能演示（探索→检定→叙事）。

5.2：chat() 认出模组抽取提示词时改吐一份合法的结构化模组 JSON，
让「上传→解析→模组库」链路在无 key 环境下同样可演示。
"""
import asyncio
import json

# 与 app.agent.module_parser.EXTRACT_PROTOCOL 对齐的识别标记
_MODULE_MARKER = '结构化抽取器'


def _extract_latest_action(messages: list[dict]) -> str:
    """从末条 user 消息截取【最新剧情推进】段落作为 mock 叙事素材。"""
    for msg in reversed(messages):
        if msg.get('role') != 'user':
            continue
        content = msg.get('content', '') or ''
        marker = '【最新剧情推进】'
        idx = content.find(marker)
        if idx >= 0:
            tail = content[idx + len(marker):].strip()
            return tail[:60] or '当前场景'
        return '当前场景'
    return '当前场景'


def _suggestions_payload(snippet: str) -> str:
    payload = {
        'suggestions': [
            {
                'text': f'（演示建议）你顺着刚才的动静望去，{snippet[:40]}……'
                        '空气里有一种说不出的违和感，似乎有什么东西正注视着调查员。',
                'check_hint': None,
            },
            {
                'text': f'（演示建议）保险起见先退到亮处——围绕「{snippet[:30]}」'
                        '稳住场面，用余光留意周围人的反应。',
                'check_hint': {'skill': '侦查', 'difficulty': 'standard', 'stake': '失败则错过关键细节'},
            },
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _module_payload(messages: list[dict]) -> str:
    """模组结构化抽取的演示产物：结构合法、字段齐全，供模组库 UI 演示。"""
    source = ' '.join(m.get('content', '') or '' for m in messages)
    snippet = source.split('【模组原文】')[-1].strip()[:40] or '当前模组'
    payload = {
        'title': '（演示）模组骨架',
        'background': f'（演示）依据原文开头「{snippet}」生成的背景概述，'
                      '用于验证模组库页面的结构化展示与房间挂载链路。',
        'tone': '（演示）克制恐怖，重氛围轻战斗',
        'hook': '（演示）一封来历不明的邀请把调查员引向现场。',
        'acts': [
            {'order': 1, 'title': '第一幕', 'summary': '（演示）调查员抵达现场并接触关键 NPC。',
             'public_goal': '弄清发生了什么', 'keeper_goal': '让玩家先看见异常再看见源头',
             'key_clues': ['现场的第一处异常', 'NPC 的闪烁其词']},
            {'order': 2, 'title': '第二幕', 'summary': '（演示）真相浮出水面，威胁时钟开始收紧。',
             'public_goal': '阻止事态恶化', 'keeper_goal': '把线索指向守秘真相',
             'key_clues': ['被刻意隐藏的记录']},
        ],
        'npcs': [{
            'name': '（演示）关键 NPC',
            'public_identity': '本地知情人',
            'hidden_motive': '（演示·仅 KP）试图掩盖自己与事件的关联',
            'player_clues': ['说话前后矛盾'],
            'misdirection': '把嫌疑引向外来者',
            'pressed_reaction': '被逼问时改用沉默与转移话题',
            'exit_plan': '若被识破则连夜离开，留下一封半真半假的信',
            'stats': {},
        }],
        'clues': [
            {'code': '', 'content': '（演示）现场遗留的关键物证', 'visibility': 'public',
             'points_to': '事件并非意外'},
            {'code': '', 'content': '（演示）只有 KP 知道的时间线矛盾', 'visibility': 'keeper',
             'points_to': '真凶的身份'},
        ],
        'clocks': [{'name': '（演示）威胁逼近', 'target': 4, 'note': '走满则事态不可逆'}],
        'endings': [{'name': '（演示）终结', 'condition': '威胁时钟走满且调查员未阻止'}],
        'key_checks': [{'skill': '侦查', 'difficulty': 'standard', 'scene': '第一幕',
                        'stake': '失败则错过关键细节'}],
        'warnings': ['（演示）本结果为 mock 客户端产出，非真实解析'],
    }
    return json.dumps(payload, ensure_ascii=False)


class MockLLMClient:
    """LLMClient 的零网络替身：chat / chat_with_tools / ping / list_models 同签名。"""

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.8,
        max_tokens: int | None = None,
        deadline: float | None = None,
        attempts: int | None = None,
        json_mode: bool = False,
    ) -> str:
        await asyncio.sleep(0.8)  # 模拟生成延迟，让前端「生成中」骨架可见
        if any(_MODULE_MARKER in (m.get('content') or '') for m in messages):
            return _module_payload(messages)
        return _suggestions_payload(_extract_latest_action(messages))

    async def chat_with_tools(
        self,
        messages: list[dict],
        *,
        tools: list[dict],
        tool_choice: str = 'auto',
        model: str | None = None,
        temperature: float = 0.8,
        max_tokens: int | None = None,
        deadline: float | None = None,
        attempts: int | None = None,
        json_mode: bool = False,
    ):
        from app.llm.provider import AssistantTurn

        await asyncio.sleep(0.5)
        # 末条消息是工具结果 → 出四段 JSON 终稿；否则先请求一次检定工具
        if messages and messages[-1].get('role') == 'tool':
            snippet = _extract_latest_action(messages)
            turn = AssistantTurn(content=json.dumps({
                'narration_public': f'（演示主持）{snippet[:40]}……你仔细查看四周，'
                                    '灯笼的光晕外似乎有什么东西一闪而过。',
                'keeper_notes': '（演示）下一次可安排一次理智检定（0/1D6）或暗骰推进威胁。',
                'options': ['举起灯笼照向光晕外', '后退一步并呼喊同伴', '假装无事发生继续观察'],
            }, ensure_ascii=False))
            return turn
        return AssistantTurn(tool_calls=[{
            'id': 'mock-call-1',
            'name': 'roll_check',
            'arguments': {'skill_name': '侦查', 'value': 50, 'difficulty': 'standard', 'reason': '观察周围动静'},
        }])

    async def ping(self) -> float:
        await asyncio.sleep(0.05)
        return 42.0  # 固定假延迟（ms）

    async def list_models(self) -> list[str]:
        return ['mock-flash', 'mock-plus']


_mock_client: MockLLMClient | None = None


def get_mock_client() -> MockLLMClient:
    global _mock_client
    if _mock_client is None:
        _mock_client = MockLLMClient()
    return _mock_client
