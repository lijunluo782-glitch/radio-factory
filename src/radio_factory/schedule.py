"""排播引擎:给一个日期,算出今天播什么。

轮换规则:rotate 时段每过一周前进一档,循环。
epoch 必须是周一,作为第 0 周。
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import yaml

from .models import Airing, Channel

CHANNEL_DIR = Path(__file__).resolve().parents[2] / "channels"


def load_channel(channel_id: str, channel_dir: Path | None = None) -> Channel:
    d = channel_dir or CHANNEL_DIR
    path = d / f"{channel_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"找不到频道配置:{path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    ch = Channel(**data)
    if ch.epoch.weekday() != 0:
        raise ValueError(f"epoch 必须是周一,当前是 {ch.epoch}(周{ch.epoch.weekday() + 1})")
    return ch


def list_channels(channel_dir: Path | None = None) -> list[str]:
    d = channel_dir or CHANNEL_DIR
    return sorted(p.stem for p in d.glob("*.yaml"))


def week_index(ch: Channel, day: date) -> int:
    """day 所在周,距 epoch 的周数。"""
    monday = day - timedelta(days=day.weekday())
    return (monday - ch.epoch).days // 7


def resolve(ch: Channel, day: date) -> Airing | None:
    """算出某天的播出内容。返回 None 表示这天不播。"""
    weekday = day.weekday() + 1
    slot = ch.slot_for(weekday)
    if slot is None or slot.mode == "off":
        return None

    idx = 0
    program = None
    if slot.programs:
        if slot.mode == "rotate":
            idx = week_index(ch, day) % len(slot.programs)
        program = slot.programs[idx]

    announce = slot.announce
    if program and program.tagline:
        announce = f"{slot.announce}{program.tagline}"

    return Airing(
        air_date=day,
        weekday=weekday,
        slot=slot,
        program=program,
        sting=ch.sting(slot.sting),
        announce=announce,
        rotation_index=idx,
    )


def rundown(ch: Channel, start: date, days: int = 21) -> list[Airing]:
    out = []
    for i in range(days):
        a = resolve(ch, start + timedelta(days=i))
        if a:
            out.append(a)
    return out


def open_line(ch: Channel, air: Airing) -> str:
    """完整开场白 = 频道名 + 今天星期几 + 领域宣告(+ 节目 tagline)。"""
    head = ch.open_line.format(
        channel=ch.name, weekday=ch.weekday_names[air.weekday - 1]
    )
    return f"{head}{air.announce}"
