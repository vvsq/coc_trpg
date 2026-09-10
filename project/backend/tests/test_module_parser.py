"""模组结构化 schema 与抽取流水线测试 — 阶段 5（goal §7）。

这些测试不碰网络、不花 token：
  - normalize_parsed 是「LLM 产物」与「KP 人工编辑」共用的唯一入口，尽量往脏数据上打
  - chunk_text / merge_parsed 是分块抽取的核心（长模组能不能抽全看这两步）
  - parse_json_payload 兜住 LLM 最常见的 JSON 输出瑕疵
"""
import json

import pytest

from app.agent.module_parser import (
    CHUNK_MAX_CHARS,
    PARSED_KEYS,
    chunk_text,
    empty_parsed,
    merge_parsed,
    normalize_parsed,
    parse_json_payload,
)


def test_empty_parsed_has_all_keys():
    parsed = empty_parsed()
    assert set(parsed) == set(PARSED_KEYS)
    assert all(parsed[key] == '' for key in ('title', 'background', 'tone', 'hook'))
    assert all(parsed[key] == [] for key in ('acts', 'npcs', 'clues', 'clocks',
                                             'endings', 'key_checks', 'warnings'))


def test_non_dict_input_degrades_to_empty():
    assert normalize_parsed(None) == empty_parsed()
    assert normalize_parsed('一段文本') == empty_parsed()
    assert normalize_parsed(['a']) == empty_parsed()


def test_unknown_top_level_keys_dropped():
    parsed = normalize_parsed({'title': '雪盲', 'evil_key': 'x', 'session': 'y'})
    assert parsed['title'] == '雪盲'
    assert 'evil_key' not in parsed and 'session' not in parsed


def test_item_field_whitelist_and_type_degrade():
    """NPC 只保留六要素 + 数值；多余键丢弃，列表型字段折成一句话。"""
    parsed = normalize_parsed({'npcs': [{
        'name': '斯考格医师',
        'public_identity': '退休村医',
        'hidden_motive': '替教团销毁病例记录',
        'player_clues': ['病例本缺页', '药柜里有冻伤膏'],
        'stats': {'attributes': {'INT': 70}},
        'hacked': 'should be dropped',
    }]})
    npc = parsed['npcs'][0]
    assert npc['name'] == '斯考格医师'
    assert npc['player_clues'] == '病例本缺页；药柜里有冻伤膏'
    assert npc['stats'] == {'attributes': {'INT': 70}}
    assert 'hacked' not in npc


def test_scalar_item_degrades_to_single_field():
    """LLM 偶尔把整个列表写成字符串数组：降级成只填关键字段的项，不整条丢弃。"""
    parsed = normalize_parsed({
        'npcs': ['守夜人老陈'],
        'clues': ['霜下的旧刻痕'],
        'clocks': ['寒灾蔓延'],
    })
    assert parsed['npcs'][0]['name'] == '守夜人老陈'
    assert parsed['clues'][0]['content'] == '霜下的旧刻痕'
    assert parsed['clues'][0]['visibility'] == 'keeper'  # 缺省按仅 KP 保守处理
    assert parsed['clocks'][0]['name'] == '寒灾蔓延'
    assert parsed['clocks'][0]['target'] == 4


def test_enum_fields_fall_back_to_safe_defaults():
    parsed = normalize_parsed({
        'clues': [{'content': 'x', 'visibility': 'PUBLIC'}],
        'key_checks': [{'skill': '侦查', 'difficulty': 'impossible'}],
    })
    assert parsed['clues'][0]['visibility'] == 'public'  # 大小写归一
    assert parsed['key_checks'][0]['difficulty'] == 'standard'  # 非法难度降级


def test_acts_sorted_by_order_and_index_backfilled():
    parsed = normalize_parsed({'acts': [
        {'order': 3, 'title': '第三幕'},
        {'title': '无序号幕'},
        {'order': 1, 'title': '第一幕'},
    ]})
    titles = [act['title'] for act in parsed['acts']]
    assert titles == ['第一幕', '第三幕', '无序号幕']
    assert [act['order'] for act in parsed['acts']] == [1, 3, 3]  # 缺失按位次回填


def test_string_fields_accept_numbers_and_lists():
    parsed = normalize_parsed({
        'title': '雪盲',
        'tone': ['克制', '挽歌'],
        'hook': 1912,
    })
    assert parsed['tone'] == '克制；挽歌'
    assert parsed['hook'] == '1912'


def test_long_values_truncated():
    parsed = normalize_parsed({'background': '字' * 5000})
    assert len(parsed['background']) == 2000


def test_normalize_is_idempotent():
    """二次归一不改变结果——PUT 反复提交同一份 parsed 必须稳定。"""
    once = normalize_parsed({'title': '雪盲', 'acts': [{'title': '第一幕'}],
                             'npcs': ['斯考格医师'], 'warnings': ['第 3 幕缺线索']})
    assert normalize_parsed(once) == once


# ---------- 分块 ----------

def test_chunk_short_text_single_chunk():
    assert chunk_text('很短的一段') == ['很短的一段']
    assert chunk_text('   ') == []


def test_chunk_packs_paragraphs_within_limit():
    paragraphs = [f'第{i}段' + '字' * 300 for i in range(20)]
    chunks = chunk_text('\n\n'.join(paragraphs), max_chars=1000, overlap=0)
    assert len(chunks) > 1
    # 每块不超限（允许段落本身超限时的硬切边界）
    assert all(len(chunk) <= 1000 for chunk in chunks)
    # 不丢内容：拼回去应覆盖全部段落的首字符
    joined = ''.join(chunks)
    for i in range(20):
        assert f'第{i}段' in joined


def test_chunk_hard_splits_single_huge_paragraph():
    """没有空行的长文（PDF 常见）必须能硬切，否则永远只有一块、超出上下文。"""
    chunks = chunk_text('字' * 5000, max_chars=1000, overlap=0)
    assert len(chunks) == 5
    assert all(len(chunk) <= 1000 for chunk in chunks)


def test_chunk_overlap_carries_previous_tail():
    """相邻块带重叠：关键信息落在切缝上时两侧都能看到。"""
    text = '\n\n'.join(['甲' * 600, '乙' * 600, '丙' * 600])
    chunks = chunk_text(text, max_chars=700, overlap=100)
    assert len(chunks) > 1
    # 后一块开头带上了前一块的尾部
    assert chunks[1].startswith(chunks[0][-100:])


# ---------- LLM 输出容错解析 ----------

def test_parse_json_payload_handles_fence_and_trailing_comma():
    assert parse_json_payload('```json\n{"a": 1,}\n```') == {'a': 1}
    assert parse_json_payload('前置说明 {"title": "雪盲"} 后置说明') == {'title': '雪盲'}


def test_parse_json_payload_rejects_non_json():
    with pytest.raises(ValueError, match='JSON'):
        parse_json_payload('抱歉，我无法完成这个请求。')
    with pytest.raises(ValueError, match='JSON'):
        parse_json_payload('[1, 2, 3]')


# ---------- 多块合并 ----------

def test_merge_takes_longer_text_and_first_title():
    merged = merge_parsed([
        {'title': '雪盲', 'background': '短背景'},
        {'title': '另一个标题', 'background': '更完整的背景描述，包含真相与三幕结构。'},
    ])
    assert merged['title'] == '雪盲'          # 首个非空优先（总览块通常最准）
    assert merged['background'].startswith('更完整的背景')  # 同字段取更长


def test_merge_npcs_by_name_merges_fields():
    merged = merge_parsed([
        {'npcs': [{'name': '斯考格医师', 'public_identity': '退休村医'}]},
        {'npcs': [{'name': '斯考格医师', 'hidden_motive': '替教团销毁病例',
                   'public_identity': '国家医院退休回乡的村医'}]},
    ])
    assert len(merged['npcs']) == 1
    npc = merged['npcs'][0]
    assert npc['hidden_motive'] == '替教团销毁病例'
    assert npc['public_identity'].startswith('国家医院')  # 取更详细的一份


def test_merge_dedupes_clues_and_renumbers():
    merged = merge_parsed([
        {'clues': [{'content': '霜下的旧刻痕', 'visibility': 'public'}]},
        {'clues': [{'content': '霜下的旧刻痕 '}, {'content': '地下室的滴水声'}]},
    ])
    assert [c['content'] for c in merged['clues']] == ['霜下的旧刻痕', '地下室的滴水声']
    assert [c['code'] for c in merged['clues']] == ['线索-01', '线索-02']


def test_merge_acts_dedupes_by_title_and_sorts_by_order():
    merged = merge_parsed([
        {'acts': [{'order': 2, 'title': '第二幕', 'summary': '短'}]},
        {'acts': [{'order': 2, 'title': '第二幕', 'summary': '更长的第二幕梗概'},
                  {'order': 1, 'title': '第一幕'}]},
    ])
    assert [a['title'] for a in merged['acts']] == ['第一幕', '第二幕']
    assert merged['acts'][1]['summary'] == '更长的第二幕梗概'


def test_merge_clocks_endings_and_checks_dedupe():
    merged = merge_parsed([
        {'clocks': [{'name': '寒灾', 'target': 4}],
         'endings': [{'name': '终结', 'condition': '时钟走满'}],
         'key_checks': [{'skill': '侦查', 'difficulty': 'hard', 'scene': '第一幕'}]},
        {'clocks': [{'name': '寒灾', 'note': '村子被冻结'}],
         'endings': [{'name': '终结', 'condition': '略'}],
         'key_checks': [{'skill': '侦查', 'difficulty': 'hard', 'scene': '第一幕',
                         'stake': '错过细节'}]},
    ])
    assert len(merged['clocks']) == 1 and merged['clocks'][0]['note'] == '村子被冻结'
    assert len(merged['endings']) == 1
    assert merged['endings'][0]['condition'] == '时钟走满'  # 取更长的（首个已更长）
    assert len(merged['key_checks']) == 1
    assert merged['key_checks'][0]['stake'] == '错过细节'


def test_merge_collects_warnings_without_duplicates():
    merged = merge_parsed([
        {'warnings': ['第三幕缺线索', 'NPC 数值缺失']},
        {'warnings': ['NPC 数值缺失', '结局条件不明']},
    ])
    assert merged['warnings'] == ['第三幕缺线索', 'NPC 数值缺失', '结局条件不明']


def test_merge_empty_parts_returns_empty_skeleton():
    assert merge_parsed([]) == empty_parsed()
    assert merge_parsed([{}]) == empty_parsed()


def test_chunk_limit_constant_is_sane():
    """分块上限是 token 成本与上下文完整性的平衡点，别被随手改小。"""
    assert CHUNK_MAX_CHARS >= 2000


# ---------- 实体名归一（分块重复的主要来源） ----------

def test_merge_clocks_with_suffix_variants():
    """实测：同一时钟被不同块写成「因果积累」与「因果积累时钟」，必须合并成一条。"""
    merged = merge_parsed([
        {'clocks': [{'name': '因果积累', 'target': 3}]},
        {'clocks': [{'name': '因果积累时钟', 'target': 5, 'note': '积满则无法回头'}]},
    ])
    assert len(merged['clocks']) == 1
    assert merged['clocks'][0]['target'] == 5          # 取较大格数
    assert merged['clocks'][0]['note'] == '积满则无法回头'


def test_merge_checks_with_skill_aliases():
    """实测：理智检定被写成 Sanity Check / SC / 理智检定，合并后不该是三条。"""
    merged = merge_parsed([
        {'key_checks': [{'skill': 'Sanity Check', 'difficulty': 'standard', 'scene': '第三幕'}]},
        {'key_checks': [{'skill': 'SC', 'difficulty': 'standard', 'scene': '第 3 幕',
                         'stake': '目睹死亡则 1D3/1D6'}]},
        {'key_checks': [{'skill': '理智检定', 'difficulty': 'standard', 'scene': '第三幕'}]},
    ])
    assert len(merged['key_checks']) == 1
    assert merged['key_checks'][0]['skill'] == 'Sanity Check'  # 保留首次出现的写法
    assert merged['key_checks'][0]['stake'] == '目睹死亡则 1D3/1D6'  # stake 取更完整的一份


def test_merge_checks_keeps_different_difficulties_separate():
    """同技能不同难度是两次检定，不能合并。"""
    merged = merge_parsed([
        {'key_checks': [{'skill': '侦查', 'difficulty': 'standard'}]},
        {'key_checks': [{'skill': '侦查', 'difficulty': 'hard'}]},
    ])
    assert len(merged['key_checks']) == 2


def test_clocks_target_clamped_to_valid_range():
    """LLM 会把"页数/阶段数"误当格数（实测出现过 100），必须夹回 2~20。"""
    merged = merge_parsed([{'clocks': [{'name': '因果积累', 'target': 100},
                                       {'name': '微弱感应', 'target': 1}]}])
    targets = {clock['name']: clock['target'] for clock in merged['clocks']}
    assert targets == {'因果积累': 20, '微弱感应': 2}


def test_merge_caps_oversized_lists_and_warns():
    """条目爆炸本身是分块跑偏的信号：裁剪的同时必须留警告，不能静默丢数据。"""
    merged = merge_parsed([
        {'endings': [{'name': f'结局{i}', 'condition': 'x'} for i in range(20)]},
    ])
    assert len(merged['endings']) == 8
    assert any('endings 条目过多' in warning for warning in merged['warnings'])


# ---------- 分块流水线（假 LLM，不花钱） ----------

class _FakeClient:
    """按序吐出预设 JSON 的假客户端，同时记录每次收到的提示词。"""

    def __init__(self, payloads: list[dict]):
        self._payloads = list(payloads)
        self.prompts: list[str] = []

    async def chat(self, messages, **_kwargs) -> str:
        self.prompts.append('\n'.join(m.get('content', '') for m in messages))
        return json.dumps(self._payloads.pop(0), ensure_ascii=False)


def test_extract_module_multi_chunk_feeds_back_known_entities(monkeypatch):
    """长模组走「总览 + 逐块」，且后续块的提示词里必须带上已抽取条目。"""
    import asyncio

    import app.agent.module_parser as parser

    parts = [
        # 0：总览（唯一定分幕结构的一次调用）
        {'title': '八月二十二日',
         'acts': [{'order': 1, 'title': '导入'}, {'order': 2, 'title': '循环'}],
         'npcs': [{'name': '老人'}], 'clocks': [{'name': '因果积累', 'target': 5}]},
        # 1~4：逐块细节（acts 一律留空/被丢弃）
        {'npcs': [{'name': '恋人'}, {'name': '老人', 'hidden_motive': '许愿者本人'}]},
        {'acts': [{'order': 9, 'title': '不该出现的碎幕'}]},
        {'endings': [{'name': 'Train Travel', 'condition': '接受现实'}]},
        {'warnings': ['第 3 块原文残缺']},
    ]
    client = _FakeClient(parts)
    monkeypatch.setattr(parser, '_pick_client', lambda model: (client, 'fake-model'))

    text = '\n\n'.join('甲' * 1500 for _ in range(8))  # 约 12k 字 → 4 块 → 触发多块路径
    parsed, model_name = asyncio.run(parser.extract_module(text))

    assert model_name == 'fake-model'
    assert len(client.prompts) == 5  # 1 次总览 + 4 块
    assert '仅供你掌握全局结构' in client.prompts[0]
    assert '【已抽取条目】' not in client.prompts[0]  # 总览时还没有已抽取内容
    assert '【已抽取条目】' in client.prompts[1]      # 第一块起就把总览结果回喂
    assert '因果积累' in client.prompts[1]            # 已登记的时钟名进了提示词
    assert '老人' in client.prompts[1]
    assert 'acts 请留空数组' in client.prompts[1]     # 明确禁止逐块重定分幕

    assert parsed['title'] == '八月二十二日'
    # 分幕只取总览的结果：逐块登记的碎幕被丢弃
    assert [act['title'] for act in parsed['acts']] == ['导入', '循环']
    assert [npc['name'] for npc in parsed['npcs']] == ['老人', '恋人']
    assert parsed['npcs'][0]['hidden_motive'] == '许愿者本人'  # 跨块补字段
    assert parsed['endings'][0]['name'] == 'Train Travel'
    assert '第 3 块原文残缺' in parsed['warnings']


def test_extract_module_single_pass_for_short_text(monkeypatch):
    import asyncio

    import app.agent.module_parser as parser

    client = _FakeClient([{'title': '雪盲'}])
    monkeypatch.setattr(parser, '_pick_client', lambda model: (client, 'fake-model'))
    parsed, _ = asyncio.run(parser.extract_module('一段很短的模组文本'))
    assert len(client.prompts) == 1  # 短文本一次调用搞定，不浪费 token
    assert parsed['title'] == '雪盲'


def test_extract_module_empty_text_raises():
    import asyncio

    import app.agent.module_parser as parser

    with pytest.raises(ValueError, match='为空'):
        asyncio.run(parser.extract_module('   \n  '))
