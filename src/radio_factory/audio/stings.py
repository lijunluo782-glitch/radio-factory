"""声音标识合成。

每天一个 3 秒的固定声音,孩子先认出声音,再认出名字。
全部程序合成 —— 零版权风险,零素材依赖,一次做完永久复用。

听力安全:所有输出统一限幅并做淡入淡出,不做突然的响度跳变。
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100
PEAK = 0.5  # 硬性峰值上限,防止孩子贴着音箱听


def _envelope(n: int, fade_s: float = 0.08) -> np.ndarray:
    f = max(1, int(fade_s * SR))
    env = np.ones(n)
    env[:f] = np.linspace(0, 1, f)
    env[-f:] = np.linspace(1, 0, f)
    return env


def _normalize(x: np.ndarray) -> np.ndarray:
    m = np.max(np.abs(x)) or 1.0
    return (x / m) * PEAK


def _t(dur: float) -> np.ndarray:
    return np.linspace(0, dur, int(SR * dur), endpoint=False)


# ------------------------------------------------------------ 音色


def sweep(dur=3.0, f0=180.0, f1=2000.0, **_) -> np.ndarray:
    """从低到高的扫频。缓升,绝不从高频直接开始。"""
    t = _t(dur)
    k = (f1 / f0) ** (1 / dur)
    phase = 2 * np.pi * f0 * ((k**t - 1) / np.log(k))
    return np.sin(phase) * _envelope(len(t), 0.15)


def bells(dur=3.0, notes=(523.25, 659.25, 783.99, 1046.5), decay=6.0, **_) -> np.ndarray:
    """清脆的高音铃串。五声音阶,不刺耳。"""
    out = np.zeros(int(SR * dur))
    step = dur / (len(notes) + 1)
    for i, f in enumerate(notes):
        start = int(i * step * SR)
        t = _t(dur - i * step)
        tone = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * f * 2.76 * t)
        tone *= np.exp(-decay * t)
        out[start : start + len(tone)] += tone[: len(out) - start]
    return out * _envelope(len(out))


def noise(dur=3.0, kind="brown", lowpass=0.15, **_) -> np.ndarray:
    """电流杂音 / 无线电底噪。"""
    n = int(SR * dur)
    w = np.random.default_rng(7).normal(0, 1, n)
    if kind == "brown":
        w = np.cumsum(w)
        w -= np.mean(w)
    # 一阶低通,避免刺耳高频
    a = lowpass
    y = np.zeros(n)
    for i in range(1, n):
        y[i] = a * w[i] + (1 - a) * y[i - 1]
    return y * _envelope(n)


def ambient(dur=3.0, base=90.0, harmonics=(1, 2, 3.5), wobble=0.6, **_) -> np.ndarray:
    """舱内环境音:低频嗡嗡,带轻微起伏。"""
    t = _t(dur)
    out = np.zeros_like(t)
    for i, h in enumerate(harmonics):
        out += np.sin(2 * np.pi * base * h * t) / (i + 2)
    out *= 1 + 0.15 * np.sin(2 * np.pi * wobble * t)
    out += 0.05 * noise(dur, lowpass=0.05)
    return out * _envelope(len(t), 0.3)


def metal(dur=3.0, strikes=3, f=1200.0, **_) -> np.ndarray:
    """金属敲击。"""
    n = int(SR * dur)
    out = np.zeros(n)
    for i in range(strikes):
        start = int(i * (dur / (strikes + 1)) * SR)
        t = _t(dur)
        tone = (
            np.sin(2 * np.pi * f * t)
            + 0.6 * np.sin(2 * np.pi * f * 1.41 * t)
            + 0.4 * np.sin(2 * np.pi * f * 2.31 * t)
        ) * np.exp(-14 * t)
        out[start : start + len(tone)] += tone[: n - start]
    return out * _envelope(n)


def pulse(dur=3.0, bpm=100.0, f=440.0, **_) -> np.ndarray:
    """节拍脉冲,用于倒计时感。"""
    n = int(SR * dur)
    out = np.zeros(n)
    period = 60.0 / bpm
    t = _t(0.12)
    beep = np.sin(2 * np.pi * f * t) * np.exp(-25 * t)
    k = 0
    while k * period < dur:
        s = int(k * period * SR)
        out[s : s + len(beep)] += beep[: n - s]
        k += 1
    return out * _envelope(n)


def chime(dur=3.0, f=880.0, **_) -> np.ndarray:
    t = _t(dur)
    tone = np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 1.5 * t)
    return tone * np.exp(-3 * t) * _envelope(len(t))


KINDS = {
    "sweep": sweep,
    "bells": bells,
    "noise": noise,
    "ambient": ambient,
    "metal": metal,
    "pulse": pulse,
    "chime": chime,
}


# ------------------------------------------------------------ 输出


def render_sting(sting, out_dir: Path) -> Path:
    fn = KINDS.get(sting.kind)
    if fn is None:
        raise ValueError(f"未知音色 {sting.kind},可选:{list(KINDS)}")
    wav = _normalize(fn(dur=sting.duration_s, **sting.params))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"sting_{sting.id}.wav"
    data = (np.clip(wav, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())
    return path


def render_all(channel, out_dir: Path) -> list[Path]:
    return [render_sting(s, out_dir) for s in channel.stings]
