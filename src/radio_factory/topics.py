"""选题池:存取、筛选、体检。

体检只看一个数:剩余条数 ÷ 每周消耗。低于 20 周报警。
不要等池子见底再想办法。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .models import Channel, Topic

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "topics"

WEEKS_PER_YEAR = 52


def load_topics(channel_id: str, data_dir: Path | None = None) -> list[Topic]:
    d = data_dir or DATA_DIR
    path = d / f"{channel_id}.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Topic(**t) for t in raw]


def save_topics(channel_id: str, topics: list[Topic], data_dir: Path | None = None) -> Path:
    d = data_dir or DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{channel_id}.json"
    path.write_text(
        json.dumps([json.loads(t.model_dump_json()) for t in topics], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


# ------------------------------------------------------------------ 体检


@dataclass
class ProgramHealth:
    program: str
    name: str
    available: int  # 还没用掉的
    target: int  # 目标储量
    per_year: float  # 年消耗
    weeks_left: float
    alarm: bool
    reasons: list[str]


def slots_per_year(ch: Channel, program_id: str) -> float:
    """一档节目一年播几期。固定档 52,三周轮换档约 17。"""
    for slot in ch.slots:
        for p in slot.programs:
            if p.id == program_id:
                if slot.mode == "rotate":
                    return WEEKS_PER_YEAR / len(slot.programs)
                return float(WEEKS_PER_YEAR)
    return 0.0


def health(ch: Channel, topics: list[Topic], alarm_weeks: float = 20.0) -> list[ProgramHealth]:
    used = {"aired", "killed"}
    by_prog: Counter[str] = Counter()
    for t in topics:
        if t.status not in used:
            by_prog[t.program] += 1

    out: list[ProgramHealth] = []
    for p in ch.programs:
        per_year = slots_per_year(ch, p.id)
        if per_year <= 0:
            continue
        avail = by_prog.get(p.id, 0)
        per_week = per_year / WEEKS_PER_YEAR
        weeks_left = avail / per_week if per_week else float("inf")
        reasons = []
        if weeks_left < alarm_weeks:
            reasons.append(f"储量仅剩 {weeks_left:.0f} 周")
        if p.target_pool and avail < p.target_pool * 0.3:
            reasons.append(f"实存 {avail} 条,不足目标 {p.target_pool} 的三成")
        out.append(
            ProgramHealth(
                program=p.id,
                name=p.name,
                available=avail,
                target=p.target_pool,
                per_year=per_year,
                weeks_left=weeks_left,
                alarm=bool(reasons),
                reasons=reasons,
            )
        )
    return out


# ------------------------------------------------------------------ 筛选


def screen(t: Topic) -> list[str]:
    """选题准入检查。返回问题列表,空表示通过。

    三关:
      1. 有转述句(7 岁孩子能一句话讲出去)
      2. 有翻转句(怪的不是那里,是这里)
      3. 有一样只有耳朵能得到的东西(演示 或 音频素材)
    """
    problems = []
    if not t.retell.strip():
        problems.append("缺转述句 —— 写不出来的选题不该进池")
    elif len(t.retell) > 40:
        problems.append(f"转述句 {len(t.retell)} 字,超过 40 字,孩子记不住")
    if not t.flip.strip():
        problems.append("缺翻转句 —— 没有'怪的不是那里,是这里'这一层")
    if not t.demo.strip() and t.asset == "none":
        problems.append("既没有演示也没有音频素材 —— 这一条只有耳朵能得到什么?")
    if not t.verified and t.status not in ("pool", "killed"):
        problems.append(f"只有 {len(t.sources)} 个来源,未过双源查证")
    return problems


def pick(topics: list[Topic], program: str, n: int = 5) -> list[Topic]:
    """从池子里挑下一批,优先挑已过筛的。"""
    cands = [t for t in topics if t.program == program and t.status == "pool"]
    cands.sort(key=lambda t: (len(screen(t)), -len(t.sources)))
    return cands[:n]


# ------------------------------------------------------------------ 状态流转

STATUS_FLOW = ["pool", "picked", "verified", "written", "aired"]


def next_status(status: str) -> str | None:
    """流水线上的下一步。aired / killed 是终态,没有下一步。"""
    if status in STATUS_FLOW[:-1]:
        return STATUS_FLOW[STATUS_FLOW.index(status) + 1]
    return None
