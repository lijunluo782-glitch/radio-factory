"""核心测试。跑法:python -m pytest tests -q"""

from datetime import date

from radio_factory import script as script_mod
from radio_factory.models import Channel, Program, Script, Segment, Slot
from radio_factory.qc import rules as qc
from radio_factory.schedule import list_channels, load_channel, open_line, resolve, rundown
from radio_factory.topics import pick, screen
from radio_factory.models import Topic


def test_all_channels_load():
    ids = list_channels()
    assert "space" in ids and "nature" in ids
    for cid in ids:
        ch = load_channel(cid)
        assert ch.epoch.weekday() == 0, "epoch 必须是周一"
        assert len(ch.slots) == 7, "一周七格必须写全,留空也要显式写 off"


def test_space_sunday_is_mailbox():
    """周日不再留空,改成信箱节目——复用一到五的选题素材,换问答外壳。"""
    ch = load_channel("space")
    a = resolve(ch, date(2026, 9, 13))
    assert a is not None
    assert a.program.id == "mailbox"
    assert a.sting.kind == "chime"


def test_nature_sunday_is_field_sound():
    """周日不再留空,改成"听一段"——真录音门槛低,直接拿录音当现象用。"""
    ch = load_channel("nature")
    a = resolve(ch, date(2026, 9, 13))
    assert a is not None
    assert a.program.id == "field_sound"
    assert a.sting.kind == "sweep"


def test_rotation_cycles_every_three_weeks():
    ch = load_channel("space")
    thursdays = [date(2026, 9, 10), date(2026, 9, 17), date(2026, 9, 24), date(2026, 10, 1)]
    names = [resolve(ch, d).program.name for d in thursdays]
    assert len(set(names[:3])) == 3, "三周内不应重复"
    assert names[3] == names[0], "第四周应回到第一档"


def test_fixed_slots_never_change():
    ch = load_channel("space")
    mondays = [date(2026, 9, 7), date(2026, 9, 14), date(2026, 9, 21), date(2026, 10, 5)]
    assert len({resolve(ch, d).program.name for d in mondays}) == 1


def test_announce_is_stable_anchor():
    """open_line() 是排播预览参考文案(rf rundown/dashboard 用),轮换只改后半句;
    实际播出的开场白改为每期手写,不再套用这份文案。"""
    ch = load_channel("space")
    for d in [date(2026, 9, 10), date(2026, 9, 17), date(2026, 9, 24)]:
        assert open_line(ch, resolve(ch, d)).startswith("小小航天队。今天是星期四。星期四,我们认识一个人。")


def test_rundown_skips_off_days():
    """两个真实频道现在周日都排了节目,off 逻辑本身不该跟着"哪天有没有内容"这种
    产品决策摇摆——用一个自建的最小频道单独验证 off 天会被 rundown 跳过。"""
    slots = [
        Slot(weekday=d, domain="d", mode="off")
        if d == 7
        else Slot(weekday=d, domain="d", mode="fixed", programs=[Program(id=f"p{d}", name=f"p{d}")])
        for d in range(1, 8)
    ]
    ch = Channel(id="x", name="测试频道", epoch=date(2026, 9, 7), slots=slots)
    assert len(rundown(ch, date(2026, 9, 7), 21)) == 18  # 21 天减 3 个周日


def _script(**kw):
    base = dict(topic_id="t", channel="space", program="lab", air_date=date(2026, 9, 8))
    base.update(kw)
    return Script(**base)


def test_qc_catches_missing_flip():
    ch = load_channel("space")
    s = _script(segments=[Segment(kind="vo", text="一段话。" * 60)])
    ids = {f.rule for f in qc.run(s, ch)}
    assert "need_flip" in ids and "need_retell" in ids and "need_preview" in ids


def test_qc_catches_long_sentence():
    ch = load_channel("space")
    s = _script(segments=[Segment(kind="vo", text="这" * 40 + "。")])
    assert any(f.rule == "sent" for f in qc.run(s, ch))


def test_qc_catches_early_jargon():
    ch = load_channel("space")
    s = _script(segments=[Segment(kind="vo", text="这是微重力造成的。")])
    assert any(f.rule == "jargon" for f in qc.run(s, ch))


def test_qc_honesty_rule():
    """声化数据必须声明是翻译过来的。"""
    ch = load_channel("space")
    bad = _script(segments=[Segment(kind="vo", text="飞船录到了木星的电波,听起来像唱歌。")])
    assert any(f.rule == "honesty" for f in qc.run(bad, ch))
    good = _script(
        segments=[Segment(kind="vo", text="飞船录到的是电波,科学家把它翻译成了声音。")]
    )
    assert not any(f.rule == "honesty" for f in qc.run(good, ch))


def test_nature_channel_specific_rules():
    """频道特有规则:拟人化、接触引导。同一套代码,不同配置。"""
    ch = load_channel("nature")
    s = Script(
        topic_id="t",
        channel="nature",
        program="skills",
        air_date=date(2026, 9, 7),
        segments=[
            Segment(kind="vo", text="它想躲开天敌,所以变成了这个颜色。"),
            Segment(kind="demo", text="下次看到了,你可以去抓一只回家。"),
        ],
    )
    ids = {f.rule for f in qc.run(s, ch)}
    assert "anthro" in ids and "contact" in ids


def test_turn_gap_same_voice_is_zero():
    ch = load_channel("space")
    narrator = Segment(kind="vo", text="旁白说话。")
    assert script_mod.turn_gap_ms(ch, narrator, narrator) == 0


def test_turn_gap_voice_change_uses_default():
    ch = load_channel("space")
    narrator = Segment(kind="vo", text="旁白说话。")
    salt = Segment(kind="vo", text="让开让开!", voice="salt")
    assert script_mod.turn_gap_ms(ch, narrator, salt) == script_mod.DEFAULT_TURN_GAP_MS


def test_turn_gap_channel_override():
    ch = load_channel("space")
    ch.turn_gap_ms = 80  # 频道自己覆盖默认间隔,跟 emotion_map 同一个模式
    narrator = Segment(kind="vo", text="旁白说话。")
    salt = Segment(kind="vo", text="让开让开!", voice="salt")
    assert script_mod.turn_gap_ms(ch, narrator, salt) == 80


def test_turn_gap_follows_designed_silence():
    ch = load_channel("space")
    silence = Segment(kind="silence", seconds=2.0)
    salt = Segment(kind="vo", text="接着说。", voice="salt")
    assert script_mod.turn_gap_ms(ch, silence, salt) == 0


def test_assemble_manifest_on_real_dialogue_script():
    """用真实脚本(陈果起头 -> 多多插话 -> 陈果接回来)验证换人说话会插间隔。

    脚本内容这次会话从"旁白 + salt 拟人插话"改成了双主持人格式(陈果/多多),
    索引跟着结构变了(开场白从 1 段拆成 3 段)——这条测试验证的是
    assemble_manifest() 的间隔逻辑本身,不是某一版文案,索引改了就更新,
    不代表逻辑坏了。
    """
    ch = load_channel("space")
    s = script_mod.load(script_mod.SCRIPT_DIR / "space_2026-09-11_how_fly.json")
    manifest = script_mod.assemble_manifest(s, ch)
    by_index = {m["index"]: m for m in manifest}

    assert by_index[10]["type"] == "silence"  # 反问后的留白

    chenguo_open = by_index[11]
    assert chenguo_open["voice"] == "chenguo"
    assert chenguo_open["gap_reason"] == "follows_designed_silence"

    duoduo_line = by_index[14]
    assert duoduo_line["voice"] == "duoduo"
    assert duoduo_line["gap_reason"] == "voice_change"
    assert duoduo_line["gap_before_ms"] == script_mod.DEFAULT_TURN_GAP_MS

    chenguo_close = by_index[15]
    assert chenguo_close["voice"] == "chenguo"
    assert chenguo_close["gap_reason"] == "voice_change"


def test_topic_screening():
    t = Topic(
        id="x", channel="space", program="lab", category="c",
        title="火星为什么是红的?", retell="", flip="", demo="", asset="none",
    )
    probs = screen(t)
    assert len(probs) == 3  # 缺转述句、缺翻转句、耳朵得不到东西


def _pickable(id_, category, **kw):
    base = dict(
        id=id_, channel="space", program="sky_life", category=category,
        title=id_, retell="转述" * 3, flip="翻转", demo="演示",
    )
    base.update(kw)
    return Topic(**base)


def test_pick_avoids_recently_scheduled_category():
    """自动排播用的排序:躲开最近已经排了播出日的类目,而不是瞎选。"""
    topics = [
        _pickable("a", "eat"),
        _pickable("b", "wash"),
        _pickable("c", "eat"),
        _pickable("recent", "eat", status="written", air_date=date(2026, 9, 7)),
    ]
    top = pick(topics, "sky_life", n=1, avoid_recent=1)[0]
    assert top.category == "wash", "eat 类目最近刚排过,应该先挑没撞车的 wash"


def test_pick_falls_back_when_no_alternative_category():
    """池子里全是同一个类目时,躲不开也得照样选,不能因为撞车就返回空。"""
    topics = [
        _pickable("a", "eat"),
        _pickable("recent", "eat", status="written", air_date=date(2026, 9, 7)),
    ]
    top = pick(topics, "sky_life", n=1, avoid_recent=1)[0]
    assert top.id == "a"
