"""核心数据模型。

设计原则:频道是配置,不是代码。
新增一个频道(动植物、身体、地球)= 写一个 YAML,不改这里。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------- 声音标识


class Sting(BaseModel):
    """每天固定的 3 秒声音标识。全部程序合成,不依赖外部素材。"""

    id: str
    kind: Literal["sweep", "bells", "noise", "metal", "ambient", "chime", "pulse"]
    duration_s: float = 3.0
    params: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


# ---------------------------------------------------------------- 节目


class Category(BaseModel):
    """节目下面的内容类别。target_pool 是储量目标,用于季度体检。"""

    id: str
    name: str
    target_pool: int = 10
    example: str = ""


class Program(BaseModel):
    """一档具体节目。轮换位下面会有多个。"""

    id: str
    name: str
    tagline: str = ""  # 开场白后半句,可变
    categories: list[Category] = Field(default_factory=list)
    structure_override: list[str] | None = None

    @property
    def target_pool(self) -> int:
        return sum(c.target_pool for c in self.categories)


# ---------------------------------------------------------------- 时段


class Slot(BaseModel):
    """一周里的一格。weekday 1=周一 ... 7=周日。"""

    weekday: int = Field(ge=1, le=7)
    domain: str  # 领域,给运营看
    announce: str = ""  # 领域宣告,一年不变 —— 孩子的锚
    sting: str | None = None
    duration_min: float = 3.5
    mode: Literal["fixed", "rotate", "recap", "off"] = "fixed"
    programs: list[Program] = Field(default_factory=list)

    @field_validator("mode", mode="before")
    @classmethod
    def _yaml_off(cls, v):
        # YAML 1.1 会把裸写的 off 解析成 False。配置里应写 "off",这里兜底。
        if v is False:
            return "off"
        if v is True:
            return "fixed"
        return v

    @field_validator("programs")
    @classmethod
    def _check(cls, v, info):
        mode = info.data.get("mode")
        if mode in ("fixed",) and len(v) != 1:
            raise ValueError("fixed 时段必须且只能有 1 档节目")
        if mode == "rotate" and len(v) < 2:
            raise ValueError("rotate 时段至少要 2 档节目")
        if mode == "off" and v:
            raise ValueError("off 时段不能挂节目")
        return v


# ---------------------------------------------------------------- 结构骨架


class StructureStep(BaseModel):
    """节目固定结构的一步。不同频道可以有不同骨架。"""

    name: str
    at_s: float | None = None
    seconds: float | None = None
    note: str = ""
    required: bool = True


# ---------------------------------------------------------------- 质检规则


class QCRule(BaseModel):
    """数据驱动的质检规则。kind 对应 qc/rules.py 里注册的检查函数。"""

    id: str
    kind: str
    severity: Literal["error", "warn"] = "error"
    params: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


# ---------------------------------------------------------------- 频道


class Channel(BaseModel):
    id: str
    name: str
    audience: str = "6-12"
    open_line: str = "{channel}。今天是{weekday}。"
    weekday_names: list[str] = Field(
        default_factory=lambda: ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    )
    epoch: date  # 排播起算日,必须是周一
    rotation_weeks: int = 3

    structure: list[StructureStep] = Field(default_factory=list)
    slots: list[Slot] = Field(default_factory=list)
    stings: list[Sting] = Field(default_factory=list)
    qc: list[QCRule] = Field(default_factory=list)
    redlines: list[str] = Field(default_factory=list)
    emotion_map: dict[str, str] = Field(default_factory=dict)  # step 名 -> 情绪标签,覆盖默认表

    def slot_for(self, weekday: int) -> Slot | None:
        return next((s for s in self.slots if s.weekday == weekday), None)

    def sting(self, sid: str | None) -> Sting | None:
        if not sid:
            return None
        return next((s for s in self.stings if s.id == sid), None)

    def program(self, pid: str) -> Program | None:
        for s in self.slots:
            for p in s.programs:
                if p.id == pid:
                    return p
        return None

    @property
    def programs(self) -> list[Program]:
        return [p for s in self.slots for p in s.programs]


# ---------------------------------------------------------------- 选题


TopicStatus = Literal["pool", "picked", "verified", "written", "aired", "killed"]


class Topic(BaseModel):
    """选题池里的一条。

    retell 是核心字段 —— 7 岁孩子能不能一句话讲给另一个 7 岁孩子听。
    写不出 retell 的选题不许进池。
    """

    id: str
    channel: str
    program: str
    category: str
    title: str  # 问句形式
    retell: str  # 转述句,"啊?"测试的载体
    flip: str = ""  # 翻转句:怪的不是那里,是这里
    analogy: str = ""  # 生活类比
    demo: str = ""  # 身体指令 / 当场演示
    asset: Literal["none", "synth", "archive"] = "none"
    status: TopicStatus = "pool"
    sources: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    air_date: date | None = None

    @property
    def verified(self) -> bool:
        return len(self.sources) >= 2


# ---------------------------------------------------------------- 脚本


SegmentKind = Literal[
    "sting",  # 声音标识
    "announce",  # 开场白 + 领域宣告
    "vo",  # 旁白
    "sfx",  # 音效
    "silence",  # designed 沉默
    "demo",  # 身体指令
    "flip",  # 翻转
    "retell",  # 可转述的一句
    "code",  # 本周暗号
    "preview",  # 明日预告
]


class Segment(BaseModel):
    kind: SegmentKind
    text: str = ""
    seconds: float | None = None
    asset: str | None = None  # sting id / 音效 id
    voice: str | None = None
    step: str = ""  # 对应 structure 里的步骤名(现象/反问/解释…),给情绪映射用
    emotion: str | None = None  # TTS 情绪标签,skeleton() 按 step 自动填,可人工覆盖

    @property
    def est_seconds(self) -> float:
        """中文播报约 4.2 字/秒。"""
        if self.seconds is not None:
            return self.seconds
        return round(len(self.text) / 4.2, 1)


class Script(BaseModel):
    topic_id: str
    channel: str
    program: str
    air_date: date
    segments: list[Segment] = Field(default_factory=list)
    waived_rules: list[str] = Field(default_factory=list)  # 人工复核后忽略的 warn 级规则 id

    @property
    def duration_s(self) -> float:
        return round(sum(s.est_seconds for s in self.segments), 1)

    @property
    def word_count(self) -> int:
        return sum(len(s.text) for s in self.segments if s.kind != "sting")

    def of_kind(self, kind: SegmentKind) -> list[Segment]:
        return [s for s in self.segments if s.kind == kind]


# ---------------------------------------------------------------- 排播结果


class Airing(BaseModel):
    air_date: date
    weekday: int
    slot: Slot
    program: Program | None
    sting: Sting | None
    announce: str
    rotation_index: int = 0
