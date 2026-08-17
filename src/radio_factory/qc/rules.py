"""质检规则注册表。

规则写在频道 YAML 里,检查函数注册在这里。
新频道要新规则时,加一个 @register 函数,不改别处。

提示词里写"请不要用术语"是不够的 —— 必须生成后自动检查。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..models import Channel, QCRule, Script

REGISTRY: dict[str, Callable[[Script, dict[str, Any], Channel], list[str]]] = {}


def register(kind: str):
    def deco(fn):
        REGISTRY[kind] = fn
        return fn

    return deco


@dataclass
class Finding:
    rule: str
    severity: str
    message: str


def run(script: Script, ch: Channel) -> list[Finding]:
    out: list[Finding] = []
    for rule in ch.qc:
        fn = REGISTRY.get(rule.kind)
        if fn is None:
            out.append(Finding(rule.id, "warn", f"未知规则类型 {rule.kind},已跳过"))
            continue
        for msg in fn(script, rule.params, ch):
            out.append(Finding(rule.id, rule.severity, msg))
    return out


# ------------------------------------------------------------ 通用规则


@register("duration")
def _duration(s: Script, p: dict, ch: Channel) -> list[str]:
    lo, hi = p.get("min_s", 150), p.get("max_s", 260)
    d = s.duration_s
    if d < lo:
        return [f"时长 {d}s,短于下限 {lo}s"]
    if d > hi:
        return [f"时长 {d}s,超过上限 {hi}s"]
    return []


@register("max_sentence_len")
def _sent_len(s: Script, p: dict, ch: Channel) -> list[str]:
    limit = p.get("chars", 28)
    bad = []
    for seg in s.segments:
        if seg.kind not in ("vo", "flip", "retell", "demo"):
            continue
        for sent in re.split(r"[。！？!?；;\n]", seg.text):
            sent = sent.strip()
            if len(sent) > limit:
                bad.append(f"句子 {len(sent)} 字超限({limit}):{sent[:20]}…")
    return bad


@register("forbid_terms")
def _forbid(s: Script, p: dict, ch: Channel) -> list[str]:
    terms = p.get("terms", [])
    allow_after = p.get("allow_after_s")  # 术语后置:某秒之后才允许
    hits = []
    t = 0.0
    for seg in s.segments:
        for term in terms:
            if term in seg.text:
                if allow_after is not None and t >= allow_after:
                    continue
                hits.append(f"第 {t:.0f}s 出现术语「{term}」")
        t += seg.est_seconds
    return hits


@register("require_segment")
def _require(s: Script, p: dict, ch: Channel) -> list[str]:
    kind = p["kind"]
    n = p.get("min_count", 1)
    got = len(s.of_kind(kind))
    if got < n:
        return [f"缺少 {kind} 段落:需要 {n} 个,实际 {got} 个"]
    return []


@register("shell_ratio")
def _shell(s: Script, p: dict, ch: Channel) -> list[str]:
    """壳层占比:台呼、暗号、预告不能挤掉知识主体。"""
    shell_kinds = set(p.get("kinds", ["sting", "announce", "code", "preview"]))
    limit = p.get("max_ratio", 0.15)
    total = s.duration_s or 1
    shell = sum(x.est_seconds for x in s.segments if x.kind in shell_kinds)
    r = shell / total
    if r > limit:
        return [f"壳层占比 {r:.0%},超过上限 {limit:.0%}"]
    return []


@register("hook_before")
def _hook(s: Script, p: dict, ch: Channel) -> list[str]:
    """开场若干秒内必须出现钩子(现象/悬念),不能先讲背景。"""
    deadline = p.get("seconds", 25)
    t = 0.0
    for seg in s.segments:
        if seg.kind in ("vo", "sfx", "demo") and t <= deadline:
            return []
        t += seg.est_seconds
    return [f"前 {deadline}s 内没有出现钩子,开场太慢"]


@register("silence_designed")
def _silence(s: Script, p: dict, ch: Channel) -> list[str]:
    """反问之后必须有留白,给孩子自己猜的时间。"""
    need = p.get("min_total_s", 1.5)
    got = sum(x.est_seconds for x in s.of_kind("silence"))
    if got < need:
        return [f"设计留白仅 {got}s,不足 {need}s —— 孩子没有时间自己猜"]
    return []


@register("number_anchor")
def _anchor(s: Script, p: dict, ch: Channel) -> list[str]:
    """数字后面必须跟身体能感觉的参照。"""
    words = p.get("anchor_words", ["就像", "相当于", "差不多是", "比", "装得下", "等于"])
    hits = []
    for seg in s.segments:
        if seg.kind not in ("vo", "flip", "retell"):
            continue
        for sent in re.split(r"[。！？!?；;\n]", seg.text):
            if re.search(r"\d", sent) and not any(w in sent for w in words):
                hits.append(f"数字缺参照物:{sent.strip()[:24]}…")
    return hits


@register("audio_safety")
def _safety(s: Script, p: dict, ch: Channel) -> list[str]:
    """听力安全。孩子可能贴着音箱听。"""
    max_hf = p.get("max_high_freq_s", 5.0)
    out = []
    for seg in s.segments:
        if seg.kind == "sfx" and seg.asset and "sweep" in (seg.asset or ""):
            if (seg.seconds or 0) > max_hf:
                out.append(f"高频演示 {seg.seconds}s,超过 {max_hf}s 上限")
    return out


@register("honesty_flag")
def _honesty(s: Script, p: dict, ch: Channel) -> list[str]:
    """声化数据必须声明是翻译过来的声音,不能说成"那里的声音"。"""
    triggers = p.get("triggers", ["等离子", "电波", "声化", "引力波", "X 射线"])
    marker = p.get("marker", ["翻译", "不是真的声音", "转换"])
    text = "".join(x.text for x in s.segments)
    if any(t in text for t in triggers) and not any(m in text for m in marker):
        return ["出现声化数据但没有声明这不是真实声音 —— 违反诚实红线"]
    return []


# ------------------------------------------------------------ 频道特有规则
# 新频道需要新规则时,在这里加一个 @register 函数,别处不改。


@register("no_anthropomorphism")
def _anthro(s: Script, p: dict, ch: Channel) -> list[str]:
    """动植物频道:不能把行为说成动物的主观意图。

    "它想要躲开天敌" -> 错;"这样能躲开天敌" -> 对。
    孩子会把拟人化当事实,这是内容缺陷不是文风选择。
    """
    words = p.get("words", ["它想", "它觉得", "它希望", "它决定", "它知道自己", "它故意"])
    hits = []
    for seg in s.segments:
        for w in words:
            if w in seg.text:
                hits.append(f"拟人化表述「{w}」—— 改成描述结果,不描述意图")
    return hits


@register("no_contact")
def _contact(s: Script, p: dict, ch: Channel) -> list[str]:
    """动植物频道:不能引导孩子去碰、抓、尝、采。"""
    words = p.get("words", ["去抓", "尝一尝", "摘一片", "碰一下它", "养一只", "挖出来"])
    hits = []
    for seg in s.segments:
        if seg.kind != "demo":
            continue
        for w in words:
            if w in seg.text:
                hits.append(f"演示环节出现接触引导「{w}」")
    return hits
