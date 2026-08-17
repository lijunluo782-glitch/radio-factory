"""核心测试。跑法:python -m pytest tests -q"""

from datetime import date

from radio_factory import script as script_mod
from radio_factory.models import Script, Segment
from radio_factory.qc import rules as qc
from radio_factory.schedule import list_channels, load_channel, open_line, resolve, rundown
from radio_factory.topics import screen
from radio_factory.models import Topic


def test_all_channels_load():
    ids = list_channels()
    assert "space" in ids and "nature" in ids
    for cid in ids:
        ch = load_channel(cid)
        assert ch.epoch.weekday() == 0, "epoch 必须是周一"
        assert len(ch.slots) == 7, "一周七格必须写全,留空也要显式写 off"


def test_sunday_is_off():
    ch = load_channel("space")
    assert resolve(ch, date(2026, 9, 13)) is None


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
    """孩子的锚是领域宣告,轮换只能改后半句。"""
    ch = load_channel("space")
    for d in [date(2026, 9, 10), date(2026, 9, 17), date(2026, 9, 24)]:
        assert open_line(ch, resolve(ch, d)).startswith("小小航天队。今天是星期四。星期四,我们认识一个人。")


def test_rundown_skips_off_days():
    ch = load_channel("space")
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
    """用真实脚本(旁白起头 -> salt 插话 -> 旁白接回来)验证换人说话会插间隔。"""
    ch = load_channel("space")
    s = script_mod.load(script_mod.SCRIPT_DIR / "space_2026-09-11_how_fly.json")
    manifest = script_mod.assemble_manifest(s, ch)
    by_index = {m["index"]: m for m in manifest}

    assert by_index[4]["type"] == "silence"  # 反问后的留白

    narrator_open = by_index[5]
    assert narrator_open["voice"] == "narrator"
    assert narrator_open["gap_reason"] == "follows_designed_silence"

    salt_line = by_index[6]
    assert salt_line["voice"] == "salt"
    assert salt_line["gap_reason"] == "voice_change"
    assert salt_line["gap_before_ms"] == script_mod.DEFAULT_TURN_GAP_MS

    narrator_close = by_index[7]
    assert narrator_close["voice"] == "narrator"
    assert narrator_close["gap_reason"] == "voice_change"


def test_topic_screening():
    t = Topic(
        id="x", channel="space", program="lab", category="c",
        title="火星为什么是红的?", retell="", flip="", demo="", asset="none",
    )
    probs = screen(t)
    assert len(probs) == 3  # 缺转述句、缺翻转句、耳朵得不到东西
