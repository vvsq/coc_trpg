"""模组文件解析 — 阶段 5（goal §7）。

职责边界（本模块是纯函数 + 无状态工具，不碰 DB、不发广播）：
  1. 文本提取：TXT / MD / PDF / DOCX → 纯文本（上传即执行，不花 token）
  2. 结构化 schema 定义与规整：LLM 抽取产物与 KP 人工修正都过同一套归一化，
     保证存进 module_scenario.parsed 的 JSON 形态唯一（下游渲染只认这一种）
  3. 抽取流水线：分块 → map（逐块抽取）/ reduce（合并去重），手动触发才花钱

依赖取舍：
  - DOCX 用标准库 zipfile 读 word/document.xml 去标签——venv 不装 python-docx
    （依赖越少越好），实测可完整取出正文段落
  - PDF 用已装的 pypdf（requirements.txt: pypdf==6.17.0）

D3/D9 铁律：本模块**只产出文本**，不写任何角色数值；一切数值变更仍只能走
app/agent/tools.py 的工具。
"""
from __future__ import annotations

import html
import io
import json
import logging
import re
import zipfile

from app.llm.config import get_light_settings, get_settings
from app.llm.provider import LLMUnavailableError, get_client, get_light_client

logger = logging.getLogger('app.agent.module_parser')

# 上传体积上限（提取后文本另受 MAX_RAW_CHARS 约束，防把整库拖爆）
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_RAW_CHARS = 300_000

# 允许的来源格式（扩展名 → source_type）
SUPPORTED_EXTENSIONS = {
    '.txt': 'txt',
    '.md': 'txt',
    '.markdown': 'txt',
    '.pdf': 'pdf',
    '.docx': 'docx',
}

_TEXT_ENCODINGS = ('utf-8', 'utf-8-sig', 'gb18030', 'big5')

_XML_TAG_RE = re.compile(r'<[^>]+>')
_PARA_END_RE = re.compile(r'</w:p\s*>')
_LINE_BREAK_RE = re.compile(r'<w:br\s*/?>')
_TAB_RE = re.compile(r'<w:tab\s*/?>')
_MULTI_BLANK_RE = re.compile(r'\n{3,}')


def normalize_text(text: str) -> str:
    """统一换行、去掉行尾空白、把 3 个以上连续空行压成 1 个空行。"""
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    lines = [line.rstrip() for line in text.split('\n')]
    return _MULTI_BLANK_RE.sub('\n\n', '\n'.join(lines)).strip()


def detect_source_type(filename: str) -> str:
    """按扩展名判定来源格式；不支持时抛 ValueError（API 层转 400）。"""
    name = (filename or '').strip().lower()
    dot = name.rfind('.')
    ext = name[dot:] if dot >= 0 else ''
    source_type = SUPPORTED_EXTENSIONS.get(ext)
    if not source_type:
        raise ValueError('仅支持 TXT / MD / PDF / DOCX 格式的模组文件')
    return source_type


def extract_text(filename: str, data: bytes) -> tuple[str, str]:
    """提取纯文本，返回 (source_type, text)。失败抛 ValueError（含可读原因）。

    调用方（POST /api/modules）负责体积校验与落库；本函数只关心格式与内容。
    """
    source_type = detect_source_type(filename)
    if not data:
        raise ValueError('文件内容为空')
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f'文件过大（上限 {MAX_UPLOAD_BYTES // 1024 // 1024}MB）')

    if source_type == 'txt':
        text = _txt_to_text(data)
    elif source_type == 'docx':
        text = _docx_to_text(data)
    else:
        text = _pdf_to_text(data)

    text = normalize_text(text)
    if not text:
        raise ValueError('未从文件中提取到任何文本（可能是扫描件/图片版 PDF）')
    return source_type, text[:MAX_RAW_CHARS]


# ==================== 各格式提取实现 ====================

def _txt_to_text(data: bytes) -> str:
    """纯文本：按常见中文编码依次尝试，全失败则用替换字符兜底（不丢整份文件）。"""
    for encoding in _TEXT_ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode('utf-8', errors='replace')


def _docx_to_text(data: bytes) -> str:
    """DOCX：取 word/document.xml，段落/换行/制表符先转义成文本，再去掉其余标签。"""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            if 'word/document.xml' not in zf.namelist():
                raise ValueError('不是有效的 DOCX（缺少 word/document.xml）')
            xml = zf.read('word/document.xml').decode('utf-8', errors='replace')
    except zipfile.BadZipFile as exc:
        raise ValueError('不是有效的 DOCX（文件已损坏或不是 Word 文档）') from exc

    xml = _PARA_END_RE.sub('\n', xml)
    xml = _LINE_BREAK_RE.sub('\n', xml)
    xml = _TAB_RE.sub('\t', xml)
    return html.unescape(_XML_TAG_RE.sub('', xml))


def _pdf_to_text(data: bytes) -> str:
    """PDF：逐页取文本后拼接。加密/损坏/无文本层都在这里转成可读错误。"""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as exc:
        raise ValueError(f'PDF 解析失败：{exc}') from exc
    except Exception as exc:  # pypdf 抛出的异常类型不稳定，统一兜底
        raise ValueError(f'PDF 解析失败：{exc}') from exc

    if reader.is_encrypted:
        # 空密码是常见"仅限制编辑"的 PDF，值得先试一次；否则明确报错
        try:
            if reader.decrypt('') == 0:
                raise ValueError('PDF 已加密，请先解除密码保护再上传')
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError('PDF 已加密，请先解除密码保护再上传') from exc

    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or '')
        except Exception:  # 单页损坏不该拖垮整份文档
            pages.append('')
    return '\n'.join(pages)


# ==================== 结构化 schema（唯一形态，LLM 产出与人工修正共用） ====================

# 顶层字段白名单：其余键一律丢弃，避免 LLM 自由发挥污染存储
PARSED_LIST_KEYS = ('acts', 'npcs', 'clues', 'clocks', 'endings', 'key_checks', 'warnings')
PARSED_STR_KEYS = ('title', 'background', 'tone', 'hook')
PARSED_KEYS = (*PARSED_STR_KEYS, *PARSED_LIST_KEYS)

# 各列表项的字段白名单（值统一按字符串处理，超长截断）
_ITEM_KEYS: dict[str, tuple[str, ...]] = {
    'acts': ('order', 'title', 'summary', 'public_goal', 'keeper_goal', 'key_clues'),
    'npcs': ('name', 'public_identity', 'hidden_motive', 'player_clues',
             'misdirection', 'pressed_reaction', 'exit_plan', 'stats'),
    'clues': ('code', 'content', 'visibility', 'points_to'),
    'clocks': ('name', 'target', 'note'),
    'endings': ('name', 'condition'),
    'key_checks': ('skill', 'difficulty', 'scene', 'stake'),
}

_STR_MAX = 2000
_LIST_MAX = 200  # 单个列表最多保留多少项
_VISIBILITIES = ('public', 'keeper')
# 与 app/rules/coc7.py 的 Difficulty 取值对齐（难度标签的展示文案在前端）
_DIFFICULTIES = ('standard', 'hard', 'extreme')


def empty_parsed() -> dict:
    """空骨架：前端与抽取失败兜底都用它，保证结构恒定。"""
    parsed: dict = {key: '' for key in PARSED_STR_KEYS}
    for key in PARSED_LIST_KEYS:
        parsed[key] = []
    return parsed


def _as_str(value, *, limit: int = _STR_MAX) -> str:
    """一律折成单行字符串：列表用「；」连接（与 npc 表的 player_clues 列语义一致）。"""
    if value is None:
        return ''
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return '；'.join(_as_str(v) for v in value if _as_str(v))[:limit]
    return str(value).strip()[:limit]


_ITEM_FALLBACK_FIELD = {'acts': 'title', 'npcs': 'name', 'clues': 'content',
                        'clocks': 'name', 'endings': 'name', 'key_checks': 'skill'}


def _normalize_item(key: str, item) -> dict | None:
    """列表项归一化：非 dict 项降级成只填关键字段的项（LLM 偶尔只给一句话）。

    两条入口（dict / 标量降级）最终都走同一段字段规整，这样 normalize_parsed
    对已归一化过的数据再跑一次结果不变（幂等）——PUT 反复提交同份 parsed 必须稳定。
    """
    if isinstance(item, dict):
        source = item
    else:
        text = _as_str(item)
        if not text:
            return None
        source = {field: '' for field in _ITEM_KEYS[key]}
        source[_ITEM_FALLBACK_FIELD[key]] = text

    out = {field: _as_str(source.get(field)) for field in _ITEM_KEYS[key]}
    if key == 'acts':
        # order 必须是可排序整数；缺失置 0，由 normalize_parsed 按位次回填
        raw_order = str(source.get('order') or '').strip()
        out['order'] = int(raw_order) if raw_order.isdigit() else 0
    if key == 'npcs':
        stats = source.get('stats')
        out['stats'] = stats if isinstance(stats, dict) else {}
    if key == 'clocks':
        # target 必须落在 2~20（与 clock 表约束一致）；LLM 常把"阶段数/页数"
        # 误当格数（实测出现过 100），越界一律夹回合法区间
        raw_target = str(source.get('target') or '').strip()
        target = int(raw_target) if raw_target.isdigit() else 4
        out['target'] = min(20, max(2, target))
    if key == 'clues':
        vis = _as_str(source.get('visibility')).lower()
        out['visibility'] = vis if vis in _VISIBILITIES else 'keeper'
    if key == 'key_checks':
        diff = _as_str(source.get('difficulty')).lower()
        out['difficulty'] = diff if diff in _DIFFICULTIES else 'standard'
    return out


def normalize_parsed(parsed) -> dict:
    """把任意来源的 parsed 归一到唯一形态（缺字段补空、非法值降级、超长截断）。

    LLM 抽取产物与 KP 人工编辑提交都走这里，因此：
      - 前端只管展示，不需要防御缺字段
      - 下游渲染（module_context.render_module_brief）可以假定结构完整
    """
    if not isinstance(parsed, dict):
        return empty_parsed()

    out = empty_parsed()
    for key in PARSED_STR_KEYS:
        out[key] = _as_str(parsed.get(key))
    for key in PARSED_LIST_KEYS:
        raw = parsed.get(key)
        if raw is None or raw == '':
            continue
        if not isinstance(raw, (list, tuple)):
            raw = [raw]
        items = []
        for item in raw[:_LIST_MAX * 2]:
            normalized = _normalize_item(key, item) if key in _ITEM_KEYS else _as_str(item)
            if normalized:
                items.append(normalized)
        out[key] = items[:_LIST_MAX]

    # 分幕按 order 升序（LLM 顺序常乱）；order 缺失的排在后面并保持出现顺序
    out['acts'] = [
        act for _, act in sorted(
            enumerate(out['acts']),
            key=lambda pair: (pair[1].get('order') or 999, pair[0]),
        )
    ]
    for index, act in enumerate(out['acts'], start=1):
        act['order'] = act.get('order') or index
    return out


# ==================== 抽取流水线（5.2：手动触发，花钱的唯一入口） ====================

# 分块参数：单块上限按经验取 4000 字（≈2.5k tokens），相邻块带 200 字重叠防
# 关键信息正好落在切缝上。块数 ≤ 3 时直接合并成一次调用——上下文完整且最省钱。
CHUNK_MAX_CHARS = 4000
CHUNK_OVERLAP = 200
SINGLE_PASS_CHUNK_LIMIT = 3

_FENCE_RE = re.compile(r'^\s*```[a-zA-Z0-9]*\s*|\s*```\s*$')
_TRAILING_COMMA_RE = re.compile(r',\s*(?=[}\]])')

EXTRACT_PROTOCOL = '''你是《克苏鲁的呼唤》第七版跑团模组的结构化抽取器。你的唯一任务是把模组原文整理成 JSON，供守秘人（KP）在跑团时使用。

输出要求（违反即视为失败）：
1. 只输出一个 JSON 对象，不要 markdown 围栏，不要任何解释性文字。
2. 严格依据原文：原文没写的内容留空字符串或空数组，**禁止编造**剧情、NPC 或数值。
3. 忠实保留原文的专有名词（人名、地名、模组特有称呼）。

字段说明：
- title：模组名
- background：故事背景与真相（可用 200~400 字概括，这是 KP 全知视角）
- tone：叙事基调与风格提示（如"挽歌基调、克制恐怖、重氛围轻战斗"）
- hook：开场钩子——用什么把调查员拉进故事
- acts：分幕/章节数组，每项 {order 序号(整数), title 幕名, summary 该幕梗概,
  public_goal 玩家可见目标, keeper_goal 守秘目标(仅 KP), key_clues 关键线索(字符串或数组)}
- npcs：核心 NPC 数组，每项 {name, public_identity 公开身份, hidden_motive 隐藏动机(仅 KP),
  player_clues 玩家可得的线索, misdirection 误导点, pressed_reaction 被逼问时的反应,
  exit_plan 死亡/离场替代方案, stats 原文给出的属性技能数值(对象, 没有就空对象)}
- clues：线索数组，每项 {code 可留空, content, visibility, points_to}
  visibility 判定：玩家在正文或对话里能直接得知 → "public"；只有 KP 知道的真相 → "keeper"
- clocks：威胁时钟数组，每项 {name, target 总格数(整数, 2~20), note 走满后果(仅 KP)}
- endings：结局数组，每项 {name, condition 触发条件(仅 KP)}
- key_checks：模组明确要求的关键检定数组，每项 {skill, difficulty(standard/hard/extreme), scene, stake 失败后果}
- warnings：存疑清单（字符串数组）——原文残缺、前后矛盾、无法判断归属的地方都记在这里，
  提醒 KP 优先人工校对。没有就留空数组。

不要输出 JSON Schema，不要输出注释，直接给数据。'''

# 多块模式先跑一次的"总览"提示：先定分幕骨架，再逐块补细节，避免各块各写一套幕次
_OVERVIEW_HINT = ('本段是模组全文（可能较长，仅供你掌握全局结构）。'
                 '请重点抽取 title / background / tone / hook 与 acts 的分幕骨架；'
                 '细节（NPC、线索、时钟、结局、检定）可留空，后续会逐段补齐。')
_CHUNK_HINT = ('本段是模组原文的第 {index}/{total} 块。请抽取本块中出现的 NPC、线索、时钟、结局与关键检定。'
               '**acts 请留空数组**（分幕结构已由总览确定，重复登记会打乱幕次）。')


def _known_hint(parts: list[dict]) -> str:
    """把已抽取的条目回喂给下一块，从源头减少重复（分块抽取最大的质量杀手）。

    实测（辉质《八月二十二日》PDF，5 块）：不回喂时同一实体被不同块各自登记，
    合并后出现「因果积累」与「因果积累时钟」这类成对重复、以及 17 个结局。
    """
    merged = merge_parsed(parts)
    lines: list[str] = []
    if merged['acts']:
        lines.append('分幕：' + ' / '.join(a['title'] for a in merged['acts'][:12]))
    if merged['npcs']:
        lines.append('NPC：' + ' / '.join(n['name'] for n in merged['npcs'][:30]))
    if merged['clocks']:
        lines.append('时钟：' + ' / '.join(clock['name'] for clock in merged['clocks'][:8]))
    if merged['endings']:
        lines.append('结局：' + ' / '.join(e['name'] for e in merged['endings'][:8]))
    if not lines:
        return ''
    return ('\n\n【已抽取条目】下列内容已经登记过，**不要重复登记**；'
            '若本块确实补充了新信息，可省略重复部分：\n- ' + '\n- '.join(lines))


def resolve_parse_model(model: str | None) -> str:
    """解析用哪个模型：显式指定 > 轻任务模型（未配则回退主模型）。

    与协同建议的分级路由同源（goal §7 4.4），因此"解析默认走便宜的快模型"，
    需要更高质量时在模组详情页手动选一个更强的模型。
    """
    chosen = (model or '').strip()
    if chosen:
        return chosen
    return get_light_settings().model


def _pick_client(model: str | None):
    """选传输客户端，返回 (client, 实际模型名)。

    模型名与轻任务模型一致时用轻任务客户端（可能跨供应商），否则用主客户端
    并在单次请求上覆盖模型名——这样"在下拉里换模型"能覆盖主/轻两种配置。
    """
    settings = get_settings()
    chosen = (model or '').strip()
    light = get_light_settings()
    if not chosen:
        return get_light_client(), light.model
    if settings.light_ready and chosen == settings.light_model.strip():
        return get_light_client(), light.model
    return get_client(), chosen


def parse_json_payload(raw: str) -> dict:
    """容错解析 LLM 输出：剥 markdown 围栏 → 截首个 { 到末个 } → 剥尾逗号 → json.loads。

    解析不出抛 ValueError（调用方据此触发一次"带原文重问"）。
    """
    text = _FENCE_RE.sub('', raw or '').strip()
    start, end = text.find('{'), text.rfind('}')
    if start == -1 or end <= start:
        raise ValueError('LLM 输出中未找到 JSON 对象')
    try:
        data = json.loads(_TRAILING_COMMA_RE.sub('', text[start:end + 1]))
    except json.JSONDecodeError as exc:
        raise ValueError(f'LLM 输出不是合法 JSON：{exc}') from exc
    if not isinstance(data, dict):
        raise ValueError('LLM 输出的顶层必须是 JSON 对象')
    return data


def chunk_text(
    raw: str,
    *,
    max_chars: int = CHUNK_MAX_CHARS,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """按空行分段贪心装箱成 ≤ max_chars 的块，相邻块带 overlap 字重叠。"""
    text = normalize_text(raw)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    paragraphs = [p for p in re.split(r'\n{2,}', text) if p.strip()]
    chunks: list[str] = []
    buf = ''
    for para in paragraphs:
        while len(para) > max_chars:  # 超长单段（无空行的长文）硬切
            if buf:
                chunks.append(buf)
                buf = ''
            chunks.append(para[:max_chars])
            para = para[max_chars:]
        if not buf:
            buf = para
        elif len(buf) + len(para) + 2 <= max_chars:
            buf = f'{buf}\n\n{para}'
        else:
            chunks.append(buf)
            buf = para
    if buf:
        chunks.append(buf)

    if overlap > 0 and len(chunks) > 1:
        merged = [chunks[0]]
        for previous, current in zip(chunks, chunks[1:]):
            tail = previous[-overlap:]
            merged.append(current if current.startswith(tail) else f'{tail}\n\n{current}')
        chunks = merged
    return chunks


# 顶层文本字段里「首个非空优先」的：模组名在多块抽取中应当一致，
# 取长反而可能被某一块的胡写（如"雪盲（续）"）覆盖掉正确标题
_FIRST_WINS_KEYS = ('title',)

# 实体名归一用的可剥后缀（见 _canon_key）
_KEY_SUFFIXES = ('时钟', '检定', '检查', '列表', '机制', '条目')

# 名字里的括号补充说明（中英括号都要剥：「理智崩坏时钟 (SC)」与「理智崩坏」
# 是同一个时钟，「Spot Hidden (侦查)」与「侦查」是同一个技能）
_PAREN_RE = re.compile(r'[（(][^）)]*[）)]')

# 技能名同义归一（分块抽取实测最容易重复的一类：理智检定被写成
# Sanity Check / SC / 理智检定 三种，合并后变成 6 条同义检定）。
# 键在下方 _SKILL_ALIASES 里统一过一遍 _canon_key。
_SKILL_ALIASES_RAW = {
    # 理智（最常被写成多种形式）
    'Sanity Check': '理智', 'San Check': '理智', 'SC': '理智',
    'Sanity': '理智', '理智检定': '理智', 'SAN': '理智',
    # 其余常用技能的英文名 → 规则书中文名
    'Spot Hidden': '侦查', 'Listen': '聆听', 'Library Use': '图书馆使用',
    'Persuade': '交涉', 'Persuasion': '交涉', '交涉类技能': '交涉', '说服': '交涉',
    'Dodge': '闪避', 'Psychology': '心理学', 'Medicine': '医学',
    'First Aid': '急救', '急救': '医学', '医学/急救': '医学',
    'Occult': '神秘学', 'Mysticism': '神秘学', 'Fighting': '格斗',
    '外语/教育': '教育', '图书馆': '图书馆使用',
}


def _canon_key(value: str) -> str:
    """实体名归一：剥括号补充说明 + 去空白 + 转小写 + 剥掉"时钟/检定"这类后缀。

    分块抽取时各块对同一实体的叫法常常差一点（实测：「因果积累」/「因果积累时钟」、
    「理智崩坏」/「理智崩坏时钟 (SC)」），不归一就会在合并阶段产出成对重复。
    """
    text = (value or '').lower()
    text = _PAREN_RE.sub('', text)          # "理智崩坏时钟 (SC)" → "理智崩坏时钟"
    text = re.sub(r'\s+', '', text)
    for suffix in _KEY_SUFFIXES:
        if len(text) > len(suffix) and text.endswith(suffix):
            text = text[: -len(suffix)]
    return text


def canon_skill(value: str) -> str:
    """技能名归一：中英混用、同义写法、多选一（"敏捷/体质"）都收敛到同一个键。

    实测分块抽取会把同一次检定写成 Sanity Check / Sanity Check (SC) / SC /
    理智检定 / Sanity 五种，还会把 "Agility or Constitution" 写成 "敏捷/体质"——
    取第一个技能名做键即可让它们合并。
    """
    text = _PAREN_RE.sub('', (value or '').lower())
    for separator in ('/', ' or ', '或', '、', '|'):
        if separator in text:
            text = text.split(separator, 1)[0]
            break
    key = _canon_key(text)
    return _SKILL_ALIASES.get(key, key)


# 别名表的键也要过一遍 _canon_key，否则 'Sanity Check' 与 'sanitycheck' 对不上
_SKILL_ALIASES = {_canon_key(k): v for k, v in _SKILL_ALIASES_RAW.items()}


def _merge_str(left: str, right: str) -> str:
    """两段文本合并：取更长的一段（LLM 分块抽取时同一字段常有详略差异）。"""
    left, right = (left or '').strip(), (right or '').strip()
    if not left:
        return right
    if not right:
        return left
    return left if len(left) >= len(right) else right


def _merge_by_key(
    items_a: list[dict],
    items_b: list[dict],
    key: str,
    fields: tuple[str, ...],
    *,
    key_fn=_canon_key,
) -> list[dict]:
    """按 key 合并两组对象数组：同 key 逐字段合并，新 key 追加在后。

    合并策略按字段类型分三种：
      - stats（对象）：浅合并，后者补前者缺的键
      - target（整数）：取较大值（威胁时钟总格数在不同块里长短不一）
      - 其余（文本）：取更长的一段（LLM 分块时同一字段常详略不同）

    key 比较走 key_fn（默认 _canon_key）：分块抽取时同一实体会被不同块写成
    不同叫法（"因果积累" / "因果积累时钟"），不归一就会产出成对重复条目。
    """
    merged: dict[str, dict] = {}
    order: list[str] = []
    for item in [*items_a, *items_b]:
        name = (item.get(key) or '').strip()
        if not name:
            continue
        fingerprint = key_fn(name)
        if fingerprint not in merged:
            merged[fingerprint] = dict(item)
            order.append(fingerprint)
            continue
        current = merged[fingerprint]
        for field in fields:
            if field == 'stats':
                stats = item.get('stats') or {}
                if stats:
                    current['stats'] = {**(current.get('stats') or {}), **stats}
                continue
            if field == 'target':
                left = int(current.get('target') or 0)
                right = int(item.get('target') or 0)
                current['target'] = max(left, right)
                continue
            current[field] = _merge_str(current.get(field, ''), item.get(field, ''))
    return [merged[fingerprint] for fingerprint in order]


# 合并结果的条目上限：超出说明分块抽取已经跑偏（实测 PDF 一次跑出 17 个结局、
# 22 个检定，其中大半是同义重复或"结局 9"这种噪声），裁剪并给出警告让人工复核
_MERGE_CAPS = {'acts': 12, 'npcs': 30, 'clues': 40,
               'clocks': 8, 'endings': 8, 'key_checks': 15}


def merge_parsed(parts: list[dict]) -> dict:
    """把多次抽取的结果合并成一份（去重 + 取长 + 重编号），再走 normalize_parsed。"""
    normalized = [normalize_parsed(part) for part in parts if isinstance(part, dict)]
    merged = empty_parsed()
    if not normalized:
        return merged

    for key in PARSED_STR_KEYS:
        for part in normalized:
            if key in _FIRST_WINS_KEYS:
                merged[key] = merged[key] or part[key]
            else:
                merged[key] = _merge_str(merged[key], part[key])

    npc_fields = tuple(f for f in _ITEM_KEYS['npcs'] if f != 'name')
    merged['npcs'] = _merge_by_key([], [n for p in normalized for n in p['npcs']], 'name', npc_fields)

    act_fields = tuple(f for f in _ITEM_KEYS['acts'] if f not in ('order', 'title'))
    merged['acts'] = _merge_by_key([], [a for p in normalized for a in p['acts']], 'title', act_fields)

    clock_fields = tuple(f for f in _ITEM_KEYS['clocks'] if f != 'name')
    merged['clocks'] = _merge_by_key([], [c for p in normalized for c in p['clocks']], 'name', clock_fields)

    # 线索按正文去重（同一线索在不同块里措辞可能略有差异，先去空白再比）；
    # 重复项不是直接丢弃，而是补齐另一块里多出来的字段（指向/来源等）
    clue_index: dict[str, dict] = {}
    clue_order: list[str] = []
    for part in normalized:
        for clue in part['clues']:
            fingerprint = re.sub(r'\s+', '', clue.get('content') or '')
            if not fingerprint:
                continue
            if fingerprint not in clue_index:
                clue_index[fingerprint] = dict(clue)
                clue_order.append(fingerprint)
                continue
            current = clue_index[fingerprint]
            current['points_to'] = _merge_str(current.get('points_to', ''),
                                              clue.get('points_to', ''))
            current['content'] = _merge_str(current.get('content', ''),
                                            clue.get('content', ''))
    merged['clues'] = [clue_index[fingerprint] for fingerprint in clue_order]
    # 线索编号统一重排，避免各块各自从 线索-01 开始
    for index, clue in enumerate(merged['clues'], start=1):
        clue['code'] = f'线索-{index:02d}'

    ending_fields = tuple(f for f in _ITEM_KEYS['endings'] if f != 'name')
    merged['endings'] = _merge_by_key([], [e for p in normalized for e in p['endings']], 'name', ending_fields)

    # 关键检定按（技能归一, 难度）去重：幕次字段各块写法不统一（「第三幕」/「第 3 幕」），
    # 纳入指纹会让同一检定反复出现（实测 PDF 一次跑出 22 条）。检定清单是给 KP 的
    # 提示性信息，同技能同难度归一条、保留首次出现的幕次说明即可。
    check_index: dict[tuple[str, str], dict] = {}
    check_order: list[tuple[str, str]] = []
    for part in normalized:
        for check in part['key_checks']:
            fingerprint = (canon_skill(check.get('skill') or ''), check.get('difficulty') or '')
            if not fingerprint[0]:
                continue
            if fingerprint not in check_index:
                check_index[fingerprint] = dict(check)
                check_order.append(fingerprint)
                continue
            current = check_index[fingerprint]
            current['stake'] = _merge_str(current.get('stake', ''), check.get('stake', ''))
    merged['key_checks'] = [check_index[fingerprint] for fingerprint in check_order]

    warnings: list[str] = []
    for part in normalized:
        for warning in part['warnings']:
            if warning not in warnings:
                warnings.append(warning)

    # 超限裁剪：条目爆炸本身就是"分块抽取跑偏"的信号，裁剪的同时必须留下警告，
    # 否则 KP 会以为模组真的只有前 8 个结局
    result = normalize_parsed(merged)
    for key, cap in _MERGE_CAPS.items():
        if len(result[key]) > cap:
            warnings.append(
                f'{key} 条目过多（{len(result[key])} 条，疑为分块重复），'
                f'已保留前 {cap} 条，请人工校对'
            )
            result[key] = result[key][:cap]
    result['warnings'] = warnings[:_LIST_MAX]
    return result


async def _extract_one(client, model_name: str, text: str, *, hint: str) -> dict:
    """抽取一块文本；JSON 解析失败时带原文重问一次（与协同/全自动同款兜底）。"""
    messages = [
        {'role': 'system', 'content': EXTRACT_PROTOCOL},
        {'role': 'user', 'content': f'{hint}\n\n【模组原文】\n{text}\n\n请按要求输出 JSON。'},
    ]
    raw = await client.chat(
        messages, model=model_name or None, temperature=0.2, json_mode=True,
    )
    try:
        return parse_json_payload(raw)
    except ValueError as first_error:
        logger.warning('模组抽取 JSON 解析失败，带原文重问一次：%s', first_error)
        repair = [
            {'role': 'system', 'content': EXTRACT_PROTOCOL},
            {'role': 'user', 'content': f'{hint}\n\n【模组原文】\n{text}'},
            {'role': 'assistant', 'content': (raw or '')[:2000]},
            {'role': 'user', 'content': '上面的输出不是合法 JSON。请只输出一个合法 JSON 对象，'
                                        '修正多余逗号/围栏/注释后重发，不要解释。'},
        ]
        raw_again = await client.chat(
            repair, model=model_name or None, temperature=0.0, json_mode=True,
        )
        return parse_json_payload(raw_again)


async def extract_module(raw_text: str, *, model: str | None = None) -> tuple[dict, str]:
    """执行一次完整抽取，返回 (归一化后的 parsed, 实际使用的模型名)。

    分块策略：≤3 块一次性抽取（上下文完整最省钱）；>3 块先跑总览定分幕骨架，
    再逐块补细节后合并——避免长模组超出单次上下文而丢后半段。
    任何失败抛 LLMUnavailableError（不可用）或 ValueError（输出无法解析）。
    """
    chunks = chunk_text(raw_text)
    if not chunks:
        raise ValueError('模组原文为空，无法解析')

    client, model_name = _pick_client(model)
    if len(chunks) <= SINGLE_PASS_CHUNK_LIMIT:
        parts = [await _extract_one(
            client, model_name, '\n\n'.join(chunks),
            hint='本段是模组原文。请完整抽取全部字段。',
        )]
    else:
        parts = [await _extract_one(client, model_name, '\n\n'.join(chunks), hint=_OVERVIEW_HINT)]
        for index, chunk in enumerate(chunks, start=1):
            hint = _CHUNK_HINT.format(index=index, total=len(chunks)) + _known_hint(parts)
            part = await _extract_one(client, model_name, chunk, hint=hint)
            # 分幕结构以总览为准：逐块再登记只会得到"约会日：22日的日常"这类
            # 与总览幕次重叠的碎幕（实测 3 幕的模组被拼成 8 个幕）
            part.pop('acts', None)
            parts.append(part)
    return merge_parsed(parts), model_name


def describe_error(exc: Exception) -> str:
    """把异常转成可直接展示给 KP 的中文原因（落 module_scenario.parse_error）。"""
    if isinstance(exc, LLMUnavailableError):
        return exc.message[:300]
    return f'{type(exc).__name__}: {exc}'[:300]
