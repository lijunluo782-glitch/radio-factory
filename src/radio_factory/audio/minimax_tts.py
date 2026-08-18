"""MiniMax T2A(文本转音频)对接。

这个仓库原来故意不做合成,只导出 tts_tasks() 任务描述——这条边界这次
被明确松开了("需要文本转音频")。这个模块只负责"调 MiniMax、把音频落盘",
不做拼接、不做混音、不做后期,那几层还在仓库外面,没有跟着松绑。

凭证放在仓库根目录的 .env 文件里(已经在 .gitignore 里,不会被提交),
一行一个 KEY=VALUE:
  MINIMAX_API_KEY=...    —— 必须
  MINIMAX_GROUP_ID=...   —— 官方 platform.minimax.io 账号才有这个概念,
                            公司代理/中转的 key 不一定有,没有就不填,
                            代码会自动跳过这个参数
  MINIMAX_API_BASE=...   —— 不是打官方 api.minimax.io 时才需要填,
                            公司如果给的是自己的网关地址,填这里
命令行里设的环境变量也认,.env 只是因为这个工具的 shell 状态不跨命令持久,
用文件更省事。

第一次真正跑合成之前,先跑一遍 list_voices(),核对 voices.yaml 里选的
那几个 voice_id 在你账号里是不是真实存在——那张表是照 MiniMax 公开文档
选的型,没拿真实 key 核验过,选错了大概率是直接报错。
"""

from __future__ import annotations

import os
from pathlib import Path

import requests

_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


def _load_dotenv() -> None:
    if not _ENV_PATH.exists():
        return
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

API_BASE = os.environ.get("MINIMAX_API_BASE", "https://api.minimax.io/v1")
DEFAULT_MODEL = "speech-02-hd"
OUT_DIR = Path(__file__).resolve().parents[3] / "out"

# script.py 的 DEFAULT_EMOTION_BY_STEP / emotion_map 用的是我们自己的创作
# 词汇("好奇开场""略带调侃"...),不是 MiniMax 认的枚举值。MiniMax 的
# emotion 参数只认这 7 个英文词,这张表负责翻译,别处不用管这层。
EMOTION_MAP = {
    "好奇开场": "surprised",
    "略带调侃": "happy",
    "展开分析": "neutral",
    "若有所思": "neutral",
    "轻松收尾": "happy",
}


class MiniMaxError(RuntimeError):
    pass


def _auth() -> tuple[str, dict]:
    """返回 (key, 附加 query 参数)。没有 Group ID 就不带这个参数,
    公司中转的 key 未必有这个概念。"""
    key = os.environ.get("MINIMAX_API_KEY")
    if not key:
        raise MiniMaxError("缺 MINIMAX_API_KEY,先在 .env 或环境变量里设好再跑")
    group = os.environ.get("MINIMAX_GROUP_ID")
    return key, ({"GroupId": group} if group else {})


def _post(url: str, retries: int = 3, **kwargs) -> requests.Response:
    """这个网关偶尔会 SSL 连接中断,重试几次再报错,别让偶发抖动打断整批合成。"""
    last_err = None
    for attempt in range(retries):
        try:
            return requests.post(url, **kwargs)
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt == retries - 1:
                raise
    raise last_err  # 不会走到这里,只是让类型检查满意


def _check(resp: requests.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        resp.raise_for_status()
        raise MiniMaxError(f"响应不是 JSON,状态码 {resp.status_code}:{resp.text[:300]}")
    base = data.get("base_resp", {})
    if base.get("status_code", 0) != 0:
        raise MiniMaxError(f"MiniMax 报错 {base.get('status_code')}:{base.get('status_msg')}")
    if not base and resp.status_code != 200:
        raise MiniMaxError(f"HTTP {resp.status_code}:{resp.text[:300]}")
    return data


def list_voices() -> list[dict]:
    """列出账号里真实可用的系统音色。核对 voices.yaml 用,不是日常流程的一部分。

    这是 POST + JSON body,不是 GET + query——跟 t2a_v2 的调用方式不一样,
    也不需要 GroupId。
    """
    key, _ = _auth()
    resp = _post(
        f"{API_BASE}/get_voice",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"voice_type": "system"},
        timeout=30,
    )
    return _check(resp).get("system_voice", [])


def synthesize(text: str, voice_setting: dict, emotion: str | None = None, model: str = DEFAULT_MODEL) -> bytes:
    """调一次 T2A,返回 mp3 字节。脚本里每个 segment 的字数远小于单次 1 万字上限,
    不用自己切分。"""
    key, extra_params = _auth()
    vs = dict(voice_setting)
    if emotion:
        vs["emotion"] = EMOTION_MAP.get(emotion, "neutral")
    resp = _post(
        f"{API_BASE}/t2a_v2",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        params=extra_params,
        json={
            "model": model,
            "text": text,
            "stream": False,
            "voice_setting": vs,
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3"},
        },
        timeout=60,
    )
    data = _check(resp)
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
