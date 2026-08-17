"""脚本层:骨架生成、TTS 任务导出。

脚本是结构化的 Segment 列表,不是一段纯文本。
音效点位在写稿阶段就定,不在后期加 —— 后期配的音效永远是装饰,
脚本里写的音效才是情节。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import yaml

from .models import Airing, Channel, Script, Segment, Topic

SCRIPT_DIR = Path(__file__).resolve().parents[2] / "data" / "scripts"
VOICE_ROSTER_PATH = Path(__file__).resolve().parents[2] / "voices.yaml"

# 默认的 step -> TTS 情绪标签映射。跟频道无关的通用基线,
# 频道要覆盖某个 step 时在 YAML 的 emotion_map 里加一行,不改这里。
DEFAULT_EMOTION_BY_STEP: dict[str, str] = {
    "开场白": "好奇开场",
    "现象": "好奇开场",
    "反问": "略带调侃",
    "解释": "展开分析",
    "模仿一下": "略带调侃",
    "翻转": "若有所思",
    "转述句": "轻松收尾",
    "明日预告": "轻松收尾",
    "本周暗号": "轻松收尾",
}


def _emotion_for(ch: Channel, step_name: str) -> str | None:
    return ch.emotion_map.get(step_name) or DEFAULT_EMOTION_BY_STEP.get(step_name)


def skeleton(ch: Channel, air: Airing, topic: Topic | None = None) -> Script:
    """按频道骨架生成空脚本框架,供编导或模型填写。

    这一步刻意不调用任何模型 —— 结构是产品决策,不该交给生成。
    """
    from .schedule import open_line

    segs: list[Segment] = []
    if air.sting:
        segs.append(
            Segment(kind="sting", asset=air.sting.id, seconds=air.sting.duration_s, step="声音标识")
        )
    segs.append(
        Segment(
            kind="announce",
            text=open_line(ch, air),
            step="开场白",
            emotion=_emotion_for(ch, "开场白"),
        )
    )

    for step in ch.structure:
        name = step.name
        if name in ("声音标识", "开场白"):
            continue
        kind = {
            "留白": "silence",
            "翻转": "flip",
            "转述句": "retell",
            "明日预告": "preview",
            "模仿一下": "demo",
            "本周暗号": "code",
        }.get(name, "vo")
        text = ""
        if topic:
            text = {
                "现象": topic.title,
                "翻转": topic.flip,
                "转述句": topic.retell,
                "模仿一下": topic.demo,
            }.get(name, "")
        segs.append(
            Segment(
                kind=kind,
                text=text,
                seconds=step.seconds if kind == "silence" else None,
                step=name,
                emotion=_emotion_for(ch, name),
            )
        )

    return Script(
        topic_id=topic.id if topic else "",
        channel=ch.id,
        program=air.program.id if air.program else "",
        air_date=air.air_date,
        segments=segs,
    )


def save(script: Script, out_dir: Path | None = None) -> Path:
    d = out_dir or SCRIPT_DIR
    d.mkdir(parents=True, exist_ok=True)
    name = f"{script.channel}_{script.air_date}_{script.program or 'x'}.json"
    path = d / name
    path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
    return path


def load(path: Path) -> Script:
    return Script(**json.loads(path.read_text(encoding="utf-8")))


# ------------------------------------------------------------------ TTS


def _load_voice_roster() -> dict:
    if not VOICE_ROSTER_PATH.exists():
        return {}
    return yaml.safe_load(VOICE_ROSTER_PATH.read_text(encoding="utf-8")) or {}


def voice_setting(voice: str | None, roster: dict | None = None) -> dict:
    """把角色 id(None/narrator/crumb/...)解析成 MiniMax 的 voice_setting。

    查不到就退回 narrator——这张表在 voices.yaml,是跨频道共享的音色资源池,
    不是本仓库要维护的"合成结果",只是把角色 id 翻成 MiniMax 认识的 voice_id。
    """
    roster = roster if roster is not None else _load_voice_roster()
    narrator = roster.get("narrator", {"voice_id": "Chinese (Mandarin)_Radio_Host"})
    entry = roster.get("characters", {}).get(voice, narrator) if voice else narrator
    return {
        "voice_id": entry.get("voice_id", narrator.get("voice_id")),
        "speed": entry.get("speed", 1.0),
        "vol": entry.get("vol", 1.0),
        "pitch": entry.get("pitch", 0),
    }


def tts_tasks(script: Script, default_voice: str = "narrator") -> list[dict]:
    """导出成 TTS 任务列表。

    对接方式:把这个列表喂给你现有的 MiniMax 合成层。
    本仓库不实现合成,只负责产出稳定的任务描述 —— 保持解耦。
    """
    roster = _load_voice_roster()
    tasks = []
    for i, seg in enumerate(script.segments):
        if seg.kind in ("sting", "sfx", "silence"):
            tasks.append(
                {
                    "index": i,
                    "type": "asset" if seg.kind != "silence" else "silence",
                    "asset": seg.asset,
                    "seconds": seg.est_seconds,
                }
            )
        elif seg.text.strip():
            tasks.append(
                {
                    "index": i,
                    "type": "tts",
                    "voice": seg.voice or default_voice,
                    "voice_setting": voice_setting(seg.voice, roster),
                    "text": seg.text,
                    "est_seconds": seg.est_seconds,
                    "kind": seg.kind,
                    "emotion": seg.emotion or DEFAULT_EMOTION_BY_STEP.get(seg.step, "展开分析"),
                }
            )
    return tasks
