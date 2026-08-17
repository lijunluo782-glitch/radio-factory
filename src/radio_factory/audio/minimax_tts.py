"""MiniMax T2A(文本转音频)对接。

这个仓库原来故意不做合成,只导出 tts_tasks() 任务描述——这条边界这次
被明确松开了("需要文本转音频")。这个模块只负责"调 MiniMax、把音频落盘",
不做拼接、不做混音、不做后期,那几层还在仓库外面,没有跟着松绑。

需要两个环境变量(别把 key 写进代码或对话里):
  MINIMAX_API_KEY   —— 从 platform.minimax.io 控制台拿
  MINIMAX_GROUP_ID  —— 同一个控制台里的 Group ID

第一次真正跑合成之前,先跑一遍 list_voices(),核对 voices.yaml 里选的
那几个 voice_id 在你账号里是不是真实存在——那张表是照 MiniMax 公开文档
选的型,没拿真实 key 核验过,选错了大概率是直接报错。
"""

from __future__ import annotations

import os
from pathlib import Path

import requests

API_BASE = os.environ.get("MINIMAX_API_BASE", "https://api.minimax.io/v1")
DEFAULT_MODEL = "speech-02-hd"
OUT_DIR = Path(__file__).resolve().parents[3] / "out"


class MiniMaxError(RuntimeError):
    pass


def _auth() -> tuple[str, str]:
    key = os.environ.get("MINIMAX_API_KEY")
    group = os.environ.get("MINIMAX_GROUP_ID")
    if not key or not group:
        raise MiniMaxError("缺 MINIMAX_API_KEY 或 MINIMAX_GROUP_ID 环境变量,先设置好再跑")
    return key, group


def _check(data: dict) -> dict:
    resp = data.get("base_resp", {})
    if resp.get("status_code", 0) != 0:
        raise MiniMaxError(f"MiniMax 报错 {resp.get('status_code')}:{resp.get('status_msg')}")
    return data


def list_voices() -> list[dict]:
    """列出账号里真实可用的系统音色。核对 voices.yaml 用,不是日常流程的一部分。"""
    key, group = _auth()
    resp = requests.get(
        f"{API_BASE}/get_voice",
        headers={"Authorization": f"Bearer {key}"},
        params={"GroupId": group, "voice_type": "system"},
        timeout=30,
    )
    resp.raise_for_status()
    return _check(resp.json()).get("system_voice", [])


def synthesize(text: str, voice_setting: dict, emotion: str | None = None, model: str = DEFAULT_MODEL) -> bytes:
    """调一次 T2A,返回 mp3 字节。脚本里每个 segment 的字数远小于单次 1 万字上限,
    不用自己切分。"""
    key, group = _auth()
    vs = dict(voice_setting)
    if emotion:
        vs["emotion"] = emotion
    resp = requests.post(
        f"{API_BASE}/t2a_v2",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        params={"GroupId": group},
        json={
            "model": model,
            "text": text,
            "stream": False,
            "voice_setting": vs,
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = _check(resp.json())
    return bytes.fromhex(data["data"]["audio"])


def synthesize_script(tasks: list[dict], out_dir: Path | None = None, prefix: str = "seg") -> list[Path]:
    """把 script.py 的 tts_tasks() 输出逐条合成,按 index 落盘成单独的 mp3。

    只到"每个 segment 有一份能播的音频"为止——拼接成一整期、加音效、混音,
    这些仍然是后期链路的事,故意不在这里做。
    """
    d = out_dir or OUT_DIR
    d.mkdir(parents=True, exist_ok=True)
    paths = []
    for t in tasks:
        if t.get("type") != "tts":
            continue
        audio = synthesize(t["text"], t["voice_setting"], t.get("emotion"))
        path = d / f"{prefix}_{t['index']:02d}_{t['kind']}.mp3"
        path.write_bytes(audio)
        paths.append(path)
    return paths
