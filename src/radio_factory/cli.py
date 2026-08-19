"""命令行入口。

  rf channels                        列出所有频道
  rf rundown space --days 21         打印排播表
  rf today space                     今天播什么
  rf stings space                    合成声音标识
  rf skeleton space 2026-09-09       生成脚本骨架
  rf check space <script.json>       跑质检
  rf health space                    选题池体检
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import script as script_mod
from . import topics as topics_mod
from .qc import rules as qc_rules
from .schedule import list_channels, load_channel, open_line, resolve, rundown

app = typer.Typer(add_completion=False, help="儿童音频电台内容工厂")
console = Console()

OUT = Path(__file__).resolve().parents[2] / "out"


def _d(s: str | None) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date() if s else date.today()


@app.command()
def channels():
    """列出所有已配置频道。"""
    t = Table("频道", "名称", "节目数", "时段", "质检规则")
    for cid in list_channels():
        ch = load_channel(cid)
        on = [s for s in ch.slots if s.mode != "off"]
        t.add_row(cid, ch.name, str(len(ch.programs)), f"{len(on)}/7", str(len(ch.qc)))
    console.print(t)


@app.command()
def rundown_cmd(
    channel: str,
    start: str = typer.Option(None, help="起始日 YYYY-MM-DD,默认今天"),
    days: int = typer.Option(21, help="天数"),
):
    """打印排播表。"""
    ch = load_channel(channel)
    t = Table("日期", "周", "节目", "模式", "轮次", "时长", "开场白")
    for a in rundown(ch, _d(start), days):
        t.add_row(
            str(a.air_date),
            ch.weekday_names[a.weekday - 1],
            a.program.name if a.program else "-",
            a.slot.mode,
            str(a.rotation_index + 1) if a.slot.mode == "rotate" else "-",
            f"{a.slot.duration_min}分",
            open_line(ch, a),
        )
    console.print(t)


app.command("rundown")(rundown_cmd)


@app.command()
def today(channel: str, day: str = typer.Option(None)):
    """今天播什么。"""
    ch = load_channel(channel)
    a = resolve(ch, _d(day))
    if a is None:
        console.print("[yellow]今天留空,不播。[/yellow]")
        raise typer.Exit()
    console.print(f"[bold]{a.program.name if a.program else a.slot.domain}[/bold]")
    console.print(f"领域:{a.slot.domain}")
    console.print(f"声音标识:{a.sting.id if a.sting else '-'}({a.sting.kind if a.sting else '-'})")
    console.print(f"开场白:{open_line(ch, a)}")
    if a.program:
        console.print(f"内容类别:{', '.join(c.name for c in a.program.categories)}")


@app.command()
def stings(channel: str, out: str = typer.Option(None)):
    """合成该频道所有声音标识为 wav。"""
    from .audio import render_all

    ch = load_channel(channel)
    d = Path(out) if out else OUT / channel / "stings"
    paths = render_all(ch, d)
    for p in paths:
        console.print(f"[green]✓[/green] {p}")


@app.command()
def skeleton(channel: str, day: str, topic_id: str = typer.Option(None)):
    """生成某天的脚本骨架。结构是产品决策,不交给模型。"""
    ch = load_channel(channel)
    a = resolve(ch, _d(day))
    if a is None:
        console.print("[yellow]这天留空。[/yellow]")
        raise typer.Exit()
    tp = None
    if topic_id:
        tp = next((t for t in topics_mod.load_topics(channel) if t.id == topic_id), None)
        if tp is None:
            console.print(f"[red]找不到选题 {topic_id}[/red]")
            raise typer.Exit(1)
    s = script_mod.skeleton(ch, a, tp)
    path = script_mod.save(s)
    console.print(f"[green]✓[/green] {path}  预估 {s.duration_s}s / {s.word_count} 字")
    console.print(f"[yellow]开场白待手写[/yellow]  参考:{open_line(ch, a)}")


@app.command()
def check(channel: str, path: str):
    """跑质检。提示词写得再好也不够,必须生成后自动检查。"""
    ch = load_channel(channel)
    s = script_mod.load(Path(path))
    findings = qc_rules.run(s, ch)
    if not findings:
        console.print(f"[green]全部通过[/green]  时长 {s.duration_s}s / {s.word_count} 字")
        raise typer.Exit()
    t = Table("级别", "规则", "问题")
    for f in findings:
        color = "red" if f.severity == "error" else "yellow"
        t.add_row(f"[{color}]{f.severity}[/{color}]", f.rule, f.message)
    console.print(t)
    console.print(f"时长 {s.duration_s}s / {s.word_count} 字")
    if any(f.severity == "error" for f in findings):
        raise typer.Exit(1)


@app.command()
def health(channel: str, alarm: float = typer.Option(20.0, help="报警线,单位周")):
    """选题池体检。低于报警线要同时降消耗 + 补量。"""
    ch = load_channel(channel)
    tps = topics_mod.load_topics(channel)
    rows = topics_mod.health(ch, tps, alarm)
    t = Table("节目", "可用", "目标", "年耗", "剩余周数", "状态")
    for r in rows:
        left = "∞" if r.weeks_left == float("inf") else f"{r.weeks_left:.0f}"
        state = "[red]报警[/red]" if r.alarm else "[green]正常[/green]"
        t.add_row(r.name, str(r.available), str(r.target), f"{r.per_year:.0f}", left, state)
    console.print(t)
    bad = [r for r in rows if r.alarm]
    if bad:
        console.print("\n[red]需要处理:[/red]")
        for r in bad:
            console.print(f"  · {r.name}:{'; '.join(r.reasons)}")


@app.command()
def dashboard(
    channel: str = typer.Argument(None, help="默认打开第一个频道"),
    port: int = typer.Option(8765, help="本地端口"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="是否自动打开浏览器"),
):
    """启动本地工作台:选题池体检、脚本质检、排播预览一屏看到。"""
    from . import dashboard as dash_mod

    dash_mod.serve(channel, port, open_browser)


@app.command()
def voices():
    """列出 MiniMax 账号里真实可用的系统音色,核对 voices.yaml 用。"""
    from .audio import minimax_tts

    try:
        vs = minimax_tts.list_voices()
    except minimax_tts.MiniMaxError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    t = Table("voice_id", "名称")
    for v in vs:
        t.add_row(v.get("voice_id", ""), v.get("voice_name", ""))
    console.print(t)


@app.command()
def synthesize(channel: str, path: str, out: str = typer.Option(None, help="输出目录,默认 out/<channel>/tts")):
    """调 MiniMax 把某个脚本逐段合成 mp3。只到"每段有音频"为止,不拼接不混音。"""
    from .audio import minimax_tts

    ch = load_channel(channel)
    s = script_mod.load(Path(path))
    tasks = script_mod.tts_tasks(s, ch)
    d = Path(out) if out else OUT / channel / "tts"
    try:
        paths = minimax_tts.synthesize_script(tasks, d)
    except minimax_tts.MiniMaxError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]完成[/green] {len(paths)} 段,存到 {d}")


@app.command()
def assemble(channel: str, path: str, tts_dir: str, out: str = typer.Option(None, help="输出文件,默认跟 tts_dir 同级")):
    """把 rf synthesize 产出的分段 mp3 拼成一整期:插入真实静音、句间交叉淡化、响度拉平。"""
    from .audio import stitch

    ch = load_channel(channel)
    s = script_mod.load(Path(path))
    d = Path(tts_dir)
    o = Path(out) if out else d.parent / f"{d.name}_assembled.mp3"
    result = stitch.stitch_script(s, ch, d, o)
    console.print(f"[green]完成[/green] {result}")


@app.command()
def screen(channel: str):
    """选题准入检查:转述句、翻转句、只有耳朵能得到的东西。"""
    tps = topics_mod.load_topics(channel)
    if not tps:
        console.print("[yellow]选题池是空的。[/yellow]")
        raise typer.Exit()
    t = Table("id", "标题", "问题")
    ok = 0
    for tp in tps:
        probs = topics_mod.screen(tp)
        if not probs:
            ok += 1
            continue
        t.add_row(tp.id, tp.title[:20], "; ".join(probs))
    console.print(t)
    console.print(f"通过 {ok}/{len(tps)}")


def main():
    app()


if __name__ == "__main__":
    main()
