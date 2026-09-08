"""4.2 规则库常量前移（原阶段 5 项）：从 docs/coc7-rules.md 抽取疯狂相关四表。

docs/coc7-rules.md 的表是阶段 1 从守秘人规则书 PDF 逐条核对的结构化 markdown，
此处脚本化解析生成 `app/rules/data/madness_tables.json`，供 san_check 工具联动
疯狂状态使用。docs 更新后重跑本脚本即可再生成（幂等）。

抽取范围：
  §6.5 疯狂发作：即时症状（1D10）
  §6.6 疯狂发作：总结症状（1D10）
  附录 恐惧症状表（表Ⅸ · D100）
  附录 躁狂症状表（表Ⅹ · D100）
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # backend/
DOC = ROOT.parents[1] / 'docs' / 'coc7-rules.md'  # 仓库根 docs/
OUT = ROOT / 'app' / 'rules' / 'data' / 'madness_tables.json'

# 粗体症状名 + 冒号说明（1D10 表行格式：| 1 | **失忆**：只记得… |）
_SYMPTOM_RE = re.compile(r'^\|\s*(\d+)\s*\|\s*\*\*(.+?)\*\*[：:]\s*(.+?)\|\s*$')
# D100 表行格式：| 1 | 洗澡恐惧症(Ablutophobia) | 对于洗涤或洗澡的恐惧 |
# 兼容恐惧表个别行尾带 ①② 标记与躁狂表的 \* 转义
_D100_RE = re.compile(r'^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\|\s*$')


def _read_doc() -> str:
    if not DOC.exists():
        sys.exit(f'规则文档不存在：{DOC}')
    return DOC.read_text(encoding='utf-8')


def _section(text: str, start_marker: str, end_marker: str | None) -> str:
    start = text.index(start_marker)
    if end_marker is None:
        return text[start:]
    end = text.index(end_marker, start)
    return text[start:end]


def parse_symptom_table(section: str) -> dict[str, dict[str, str]]:
    """1D10 症状表：| N | **名称**：说明 | → {N: {name, desc}}"""
    out: dict[str, dict[str, str]] = {}
    for line in section.splitlines():
        m = _SYMPTOM_RE.match(line.strip())
        if m:
            roll, name, desc = m.groups()
            out[roll] = {'name': name.strip(), 'desc': desc.strip()}
    return out


def parse_d100_table(section: str) -> dict[str, dict[str, str]]:
    """D100 表：| N | 名称 | 说明 | → {N: {name, desc}}"""
    out: dict[str, dict[str, str]] = {}
    for line in section.splitlines():
        m = _D100_RE.match(line.strip())
        if m:
            roll, name, desc = m.groups()
            if not roll.isdigit() or not (1 <= int(roll) <= 100):
                continue
            name = name.replace('\\*', '').strip()
            out[roll] = {'name': name, 'desc': desc.strip()}
    return out


def main() -> None:
    text = _read_doc()

    immediate = parse_symptom_table(
        _section(text, '### 6.5 疯狂发作：即时症状', '### 6.6 疯狂发作：总结症状'))
    summary = parse_symptom_table(
        _section(text, '### 6.6 疯狂发作：总结症状', '### 6.7 潜在疯狂与现实认知检定'))
    phobias = parse_d100_table(
        _section(text, '## 附录：恐惧症状表', '## 附录：躁狂症状表'))
    manias = parse_d100_table(_section(text, '## 附录：躁狂症状表', None))

    # 完整性校验：2 张 1D10 表各 10 行，2 张 D100 表各 100 行
    for label, table, expect in (
        ('即时症状', immediate, 10), ('总结症状', summary, 10),
        ('恐惧症状', phobias, 100), ('躁狂症状', manias, 100),
    ):
        if len(table) != expect:
            sys.exit(f'{label}表抽取行数 {len(table)} != {expect}，docs 格式可能已变化，请人工核对')

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        '_source': 'docs/coc7-rules.md §6.5/§6.6 + 附录表Ⅸ/表Ⅹ（规则书 p.132-137 核对）',
        'immediate_symptoms': immediate,
        'summary_symptoms': summary,
        'phobias': phobias,
        'manias': manias,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'OK -> {OUT}（即时{len(immediate)}/总结{len(summary)}/恐惧{len(phobias)}/躁狂{len(manias)}）')


if __name__ == '__main__':
    main()
