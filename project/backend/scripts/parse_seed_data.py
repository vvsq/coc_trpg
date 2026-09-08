"""把 other/ 的两个人工整理文档解析成 app/seed/*.json（运行时唯一数据源）。

数据源格式（人工维护）：
  coc七版技能表.txt  行格式: `N.名称,基础值,` + 若干 `- 描述` 行
      名称形态: `会计` / `格斗(斗殴)` / `技艺①(表演、美术...):1` / `计算机使用 Ω`
      基础值:   `5` / `DEX/2` / `EDU` / 空(自定义)
  职业列表.txt       行格式: `N.职业名,信用min-max,公式,技能项...,自由数。描述`
      公式:     `教育×4` / `教育×2＋敏捷×2` / `教育×2＋力量或敏捷×2`（"或"=任选）
      技能项:   `会计` / `艺术与手艺(表演)` / `(取悦、话术、恐吓、说服):2`
                （分组项内可含带括号的技能，如 `其他语言(欧洲)`）

用法: python -X utf8 scripts/parse_seed_data.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # COC_project/
SKILL_TXT = ROOT / 'other' / 'table' / 'coc七版技能表.txt'
JOB_TXT = ROOT / 'other' / 'table' / '职业列表.txt'
OUT_DIR = Path(__file__).resolve().parents[1] / 'app' / 'seed'

ATTR_CN = {
    '力量': 'STR', '体质': 'CON', '体型': 'SIZ', '敏捷': 'DEX', '外貌': 'APP',
    '智力': 'INT', '意志': 'POW', '教育': 'EDU', '幸运': 'LUK',
}
ERA_PATTERNS = [
    ('（原作向）', 'classical'), ('(原作向)', 'classical'),
    ('（古典）', 'classical'), ('(古典)', 'classical'),
    ('（现代）', 'modern'), ('(现代)', 'modern'),
]

CIRCLED = '①②③'


def split_era(name: str) -> tuple[str, str | None]:
    """从名字中剥离时代标记，返回 (干净名字, era 或 None)。"""
    for mark, era in ERA_PATTERNS:
        if mark in name:
            return name.replace(mark, '').strip(), era
    return name, None


def split_circled(name: str) -> tuple[str, int]:
    """'技艺①' -> ('技艺', 1)；'会计' -> ('会计', 0)。"""
    if name and name[-1] in CIRCLED:
        return name[:-1], CIRCLED.index(name[-1]) + 1
    return name, 0


def parse_base(raw: str) -> tuple[int | None, str]:
    """基础值: '5' -> (5, '')；'DEX/2' -> (None, 'DEX/2')；'' -> (None, '')。"""
    raw = raw.strip()
    if raw.isdigit():
        return int(raw), ''
    return None, raw


# ---------------------------------------------------------------- 技能表


def parse_skill_title(title: str) -> dict:
    """解析技能名: 分组(带候选与pick) / 单专业 / 普通技能。"""
    modern = 'Ω' in title
    title = title.replace('Ω', '').strip()

    pick, candidates = 0, []
    m = re.search(r'\(([^()]+)\):(\d+)$', title)
    if m:  # 分组: 技艺①(表演、美术...):1
        title, candidates, pick = title[:m.start()].strip(), \
            [c.strip() for c in m.group(1).split('、')], int(m.group(2))

    detail = ''
    m = re.search(r'\(([^()]+)\)$', title)
    if m:  # 单专业: 格斗(斗殴)
        title, detail = title[:m.start()].strip(), m.group(1)

    name, slot = split_circled(title)
    return {'name': name, 'slot': slot, 'detail': detail,
            'modern_only': modern, 'pick': pick, 'candidates': candidates}


def parse_skills(text: str) -> list[dict]:
    skills: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^(\d+)\.(.*)$', line)
        if m and not line.startswith('-'):  # 新技能条目
            if cur:
                skills.append(cur)
            no = int(m.group(1))
            parts = m.group(2).split(',')
            title, base_raw = parts[0].strip(), parts[1] if len(parts) > 1 else ''
            cur = parse_skill_title(title)
            cur['id'] = no
            cur['base'], cur['base_expr'] = parse_base(base_raw)
            cur['description'] = ''
        elif cur is not None and line.startswith('-'):
            cur['description'] += line.lstrip('- ').strip() + '\n'
    if cur:
        skills.append(cur)
    return skills


# ---------------------------------------------------------------- 职业列表


def parse_formula(text: str) -> list[dict]:
    """'教育×2＋力量或敏捷×2' -> [{'multiplier':2,'candidates':['EDU']}, {'multiplier':2,'candidates':['STR','DEX']}]"""
    terms = []
    for part in re.split(r'[＋+]', text.strip()):
        part = part.strip()
        m = re.match(r'^(.+?)\s*×\s*(\d+)$', part)
        if not m:
            raise ValueError(f'无法解析公式片段: {part!r}（原文: {text!r}）')
        candidates = []
        for cn in m.group(1).split('或'):
            cn = cn.strip()
            if cn not in ATTR_CN:
                raise ValueError(f'未知属性名: {cn!r}（原文: {text!r}）')
            candidates.append(ATTR_CN[cn])
        terms.append({'multiplier': int(m.group(2)), 'candidates': candidates})
    return terms


def parse_skill_item(text: str) -> dict:
    """职业行里的一个技能项 -> fixed / group。"""
    text = text.strip()
    m = re.match(r'^\((.+)\):(\d+)$', text, re.S)
    if m:  # 分组项: (取悦、话术、恐吓、说服):2（内部可含带括号技能）
        options = []
        for opt in m.group(1).split('、'):
            opt = opt.strip()
            om = re.match(r'^(.+)\(([^()]+)\)$', opt)
            if om and not om.group(2).isdigit():
                options.append({'name': om.group(1).strip(), 'detail': om.group(2)})
            else:
                options.append({'name': opt, 'detail': ''})
        return {'type': 'group', 'pick': int(m.group(2)), 'options': options}
    name, detail = text, ''
    m = re.match(r'^(.+)\(([^()]+)\)$', text)
    if m:  # 普通项带专业: 艺术与手艺(表演)
        name, detail = m.group(1).strip(), m.group(2)
    return {'type': 'fixed', 'name': name, 'detail': detail}


def parse_job_line(line: str) -> dict:
    # 1) 定位最后一个 ",数字。" —— 之前是技能项，之后是描述
    marks = list(re.finditer(r',(\d+)。', line))
    if not marks:
        raise ValueError(f'未找到自由数与描述的分隔: {line[:60]!r}')
    m = marks[-1]
    free_picks = int(m.group(1))
    if free_picks > 10:
        raise ValueError(f'自由数异常({free_picks})，疑似误判分隔点: {line[:60]!r}')
    head, intro = line[:m.start()], line[m.end():].strip()

    # 2) 头部逗号分段: [编号.职业名, 信用, 公式, 技能项...]
    parts = [p.strip() for p in head.split(',') if p.strip()]
    if len(parts) < 3:
        raise ValueError(f'段数不足: {line[:60]!r}')
    no, raw_name = parts[0].split('.', 1)
    name, era = split_era(raw_name)
    credit_min, credit_max = (int(x) for x in parts[1].split('-'))
    formula = parse_formula(parts[2])

    # 3) 技能项 -> 固定 / 分组
    fixed_skills: list[dict] = []
    skill_groups: list[dict] = []
    for item in parts[3:]:
        parsed = parse_skill_item(item)
        if parsed['type'] == 'fixed':
            fixed_skills.append({'name': parsed['name'], 'slot': 0,
                                 'detail': parsed['detail'], 'modern_only': False})
        else:
            skill_groups.append({'mark': f'G{len(skill_groups) + 1}',
                                 'pick': parsed['pick'], 'options': [
                                     {'name': o['name'], 'slot': 0, 'detail': o['detail'],
                                      'modern_only': False} for o in parsed['options']]})

    return {
        'id': int(no), 'name': name, 'aliases': [], 'era': era,
        'credit_min': credit_min, 'credit_max': credit_max,
        'point_formula': formula, 'fixed_skills': fixed_skills,
        'skill_groups': skill_groups, 'free_picks': free_picks,
        'contacts': '', 'intro': intro,
    }


def parse_jobs(text: str) -> list[dict]:
    jobs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not re.match(r'^\d+\.', line):
            continue
        job = parse_job_line(line)
        slash = [p.strip() for p in job['name'].split('/') if p.strip()]
        if len(slash) > 1:
            job['name'], job['aliases'] = slash[0], slash[1:]
        jobs.append(job)
    return jobs


# ---------------------------------------------------------------- 主流程


def main() -> None:
    skills = parse_skills(SKILL_TXT.read_text(encoding='utf-8'))
    jobs = parse_jobs(JOB_TXT.read_text(encoding='utf-8'))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / 'skills.json').write_text(
        json.dumps(skills, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT_DIR / 'occupations.json').write_text(
        json.dumps(jobs, ensure_ascii=False, indent=2), encoding='utf-8')

    expr = [s['name'] for s in skills if s['base_expr']]
    grouped = [s['name'] for s in skills if s['pick']]
    empty_base = [s['name'] for s in skills if s['base'] is None and not s['base_expr']]
    print(f'技能 {len(skills)} 条（表达式基础值: {expr}；分组技能 {len(grouped)} 条；无基础值: {empty_base}）')
    print(f'职业 {len(jobs)} 个；含分组技能的职业 {sum(1 for j in jobs if j["skill_groups"])} 个')

    # 抽样核对
    for j in (jobs[0], jobs[1], jobs[3], jobs[213]):
        f = '＋'.join('或'.join(t['candidates']) + f'×{t["multiplier"]}' for t in j['point_formula'])
        print(f"\n[{j['id']}] {j['name']} era={j['era']} 信誉[{j['credit_min']},{j['credit_max']}] 公式={f} 自由={j['free_picks']}")
        print('  固定:', '、'.join(s['name'] + (f"({s['detail']})" if s['detail'] else '') for s in j['fixed_skills']))
        for g in j['skill_groups']:
            print(f"  {g['mark']} 选{g['pick']}: {'、'.join(o['name'] + (f'({o['detail']})' if o['detail'] else '') for o in g['options'])}")
        print('  简介:', j['intro'][:40], '...')


if __name__ == '__main__':
    sys.exit(main())
