"""本地工作台:选题池体检、脚本质检、排播预览,加上人工处理动作。

只读 data/ 和 channels/ 现有文件,不新增存储 —— 写操作也是直接改那两个
目录下的 JSON,改完 303 重定向回 GET,浏览器看到的永远是磁盘上的最新状态。
"""

from __future__ import annotations

import html
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import script as script_mod
from . import topics as topics_mod
from .models import Channel, Script, Topic
from .qc import rules as qc_rules
from .schedule import list_channels, load_channel, open_line, resolve, rundown

SCRIPT_DIR = Path(__file__).resolve().parents[2] / "data" / "scripts"

CSS = """
:root{
  --bg:#fff8ee; --panel:#ffffff; --text:#4a3b2e; --muted:#a3927f; --border:#f1e3cd;
  --ok:#2fae72; --ok-bg:#e4f7ec; --warn:#e5992e; --warn-bg:#fff2da; --alarm:#f2665f; --alarm-bg:#ffe8e6;
  --accent:#ff8a5b; --accent-bg:#ffe9dc; --accent-2:#7c6ff0; --accent-2-bg:#ece9ff;
  --sidebar:#fff1dc; --sidebar-panel:#fffaf1; --sidebar-text:#6b5642; --sidebar-muted:#b7a48d;
  --sidebar-active:#ffffff; --sidebar-badge:#ffe3bf;
  --c-topics:#ff8a5b; --c-topics-bg:#ffe9dc;
  --c-scripts:#7c6ff0; --c-scripts-bg:#ece9ff;
  --c-rundown:#2ec4b6; --c-rundown-bg:#dcf7f3;
  --c-overview:#ff5c8a; --c-overview-bg:#ffe1ea;
  --radius:16px; --radius-sm:10px;
  --shadow:0 2px 10px rgba(150,110,60,.08), 0 1px 2px rgba(150,110,60,.06);
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#241d2b; --panel:#2f2637; --text:#f4e9da; --muted:#a998a6; --border:#3d3345;
    --ok:#6fe3a4; --ok-bg:#1d3a2c; --warn:#ffcf7a; --warn-bg:#463218; --alarm:#ff9a92; --alarm-bg:#4a2222;
    --accent:#ffa06a; --accent-bg:#4a3324; --accent-2:#a79bff; --accent-2-bg:#332d55;
    --sidebar:#1c1622; --sidebar-panel:#251d2d; --sidebar-text:#ecdfd0; --sidebar-muted:#8f7e93;
    --sidebar-active:#332a3d; --sidebar-badge:#3d3345;
    --c-topics:#ffa06a; --c-topics-bg:#4a3324;
    --c-scripts:#a79bff; --c-scripts-bg:#332d55;
    --c-rundown:#5fe0d1; --c-rundown-bg:#183a37;
    --c-overview:#ff85a8; --c-overview-bg:#4a2432;
    --shadow:0 2px 12px rgba(0,0,0,.3);
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font-family:-apple-system,"Microsoft YaHei","PingFang SC",Segoe UI,sans-serif;line-height:1.6}
.shell{display:flex;min-height:100vh}
aside{width:246px;flex:none;background:var(--sidebar);color:var(--sidebar-text);
  padding:20px 16px;display:flex;flex-direction:column;gap:20px}
.brand{display:flex;align-items:center;gap:11px}
.brand-badge{width:42px;height:42px;border-radius:14px 16px 14px 18px;
  background:linear-gradient(135deg,var(--accent),var(--c-overview));color:#fff;
  display:flex;align-items:center;justify-content:center;font-weight:700;font-size:15px;flex:none;
  box-shadow:var(--shadow)}
.brand-name{font-size:15px;font-weight:700;color:var(--sidebar-text)}
.brand-sub{font-size:11px;color:var(--sidebar-muted)}
.chswitch{position:relative}
.chswitch::after{content:"▾";position:absolute;right:12px;top:50%;transform:translateY(-50%);
  color:var(--sidebar-muted);font-size:12px;pointer-events:none}
.chswitch-select{width:100%;font-size:13px;font-weight:700;padding:9px 30px 9px 12px;
  border-radius:12px;border:1px solid var(--sidebar-badge);background:var(--sidebar-panel);
  color:var(--sidebar-text);cursor:pointer;appearance:none;-webkit-appearance:none}
.navgroup{background:var(--sidebar-panel);border-radius:var(--radius);padding:6px;
  display:flex;flex-direction:column;gap:2px}
.navitem{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 12px;
  border-radius:var(--radius-sm);color:var(--sidebar-text);text-decoration:none;font-size:13.5px;
  font-weight:600;transition:transform .12s ease}
.navitem:hover{background:var(--sidebar-badge);transform:translateX(1px)}
.navitem.active{background:var(--item-accent,var(--accent));color:#fff}
.navitem.active[data-key="topics"]{--item-accent:var(--c-topics)}
.navitem.active[data-key="scripts"]{--item-accent:var(--c-scripts)}
.navitem.active[data-key="rundown"]{--item-accent:var(--c-rundown)}
.navitem.active[data-key=""]{--item-accent:var(--c-overview)}
.navcount{font-size:11px;background:var(--sidebar-badge);color:var(--sidebar-text);
  border-radius:999px;padding:1px 8px;min-width:18px;text-align:center;font-weight:700}
.navitem.active .navcount{background:rgba(255,255,255,.3);color:#fff}
.navcount.zero{opacity:.45}
main{flex:1;padding:28px 34px 60px;max-width:1080px}
h1{margin:0 0 4px;font-size:21px;font-weight:800}
.pagesub{color:var(--muted);font-size:12.5px;margin:0 0 22px}
section{margin-bottom:30px}
section h2{font-size:14.5px;margin:0 0 12px;font-weight:700;display:flex;align-items:center;gap:6px}
table{width:100%;border-collapse:separate;border-spacing:0;background:var(--panel);border:1px solid var(--border);
  border-radius:var(--radius);overflow:hidden;font-size:13px;box-shadow:var(--shadow)}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top}
tr:last-child td{border-bottom:none}
tbody tr:hover{background:var(--bg)}
th{color:var(--muted);font-weight:700;font-size:11.5px;background:var(--bg)}
code{font-size:12px;background:var(--bg);padding:2px 6px;border-radius:6px}
.muted{color:var(--muted)}
.empty{padding:26px;text-align:center;color:var(--muted);background:var(--panel);
  border:1px dashed var(--border);border-radius:var(--radius);font-size:13px}
.cardgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px}
.statcard{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
  padding:16px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:8px}
.statcard-head{display:flex;justify-content:space-between;align-items:center}
.statcard-title{font-weight:700;font-size:13.5px}
.statcard-title a{color:inherit;text-decoration:none}
.statcard-title a:hover{text-decoration:underline}
.statcard-num{font-size:22px;font-weight:800}
.statcard-num small{font-size:12px;font-weight:600;color:var(--muted)}
.statcard-reason{font-size:11.5px;color:var(--muted)}
.tag{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;white-space:nowrap;font-weight:600}
.tag-ok{color:var(--ok);background:var(--ok-bg)}
.tag-warn{color:var(--warn);background:var(--warn-bg)}
.tag-alarm{color:var(--alarm);background:var(--alarm-bg)}
.tag-status{color:var(--muted);background:var(--bg);border:1px solid var(--border)}
.bar-track{display:inline-block;width:84px;height:8px;background:var(--border);border-radius:999px;
  vertical-align:middle;margin-right:6px;overflow:hidden}
.bar-fill{height:100%;border-radius:999px}
.bar-ok{background:linear-gradient(90deg,var(--ok),var(--c-rundown))}
.bar-alarm{background:linear-gradient(90deg,var(--alarm),var(--warn))}
footer{padding:14px 30px 34px;font-size:12px}
.actions{display:flex;gap:6px;flex-wrap:wrap}
button,.btn{font-size:12.5px;padding:6px 13px;border-radius:999px;border:1px solid var(--border);
  background:var(--panel);color:var(--text);cursor:pointer;font-weight:600;transition:transform .1s ease}
button:hover,.btn:hover{transform:translateY(-1px)}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.danger{color:var(--alarm);border-color:var(--alarm)}
button.warn{color:var(--warn);border-color:var(--warn)}
form.inline{display:inline}
details{margin-top:4px}
details summary{cursor:pointer;font-size:12.5px;color:var(--accent);font-weight:600}
.editform{margin-top:8px;padding:12px;border:1px dashed var(--border);border-radius:var(--radius-sm);
  display:flex;flex-direction:column;gap:6px;background:var(--bg)}
.editform label{font-size:11px;color:var(--muted);font-weight:600}
.editform input,.editform select,.editform textarea{font-size:13px;padding:6px 8px;
  border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--panel);color:var(--text);width:100%}
.finding-row{display:flex;justify-content:space-between;gap:10px;align-items:center;
  padding:6px 0;border-bottom:1px solid var(--border);font-size:12.5px}
.finding-row:last-child{border-bottom:none}
.finding-row.waived{opacity:.5}
.seclist{display:flex;flex-direction:column;gap:10px;margin-top:8px}
.segcard{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
  padding:14px 16px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:8px}
.segcard-head{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted);font-weight:700}
.segcard-idx{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;
  border-radius:999px;background:var(--c-scripts-bg);color:var(--c-scripts);font-size:11px;font-weight:800}
.segcard-fixed{color:var(--muted);font-size:13px}
.segcard textarea{width:100%;min-height:60px;font-size:13.5px;line-height:1.65;padding:10px 12px;
  border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
  resize:vertical}
.segcard form{display:flex;flex-direction:column;gap:8px}
.segcard form button{align-self:flex-end}
td select{font-size:12px;padding:4px 8px;border:1px solid var(--border);border-radius:var(--radius-sm);
  background:var(--panel);color:var(--text)}
.assign-form{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.rangebar{display:flex;gap:10px;align-items:center;margin-bottom:16px;font-size:12.5px}
.rangebar a{color:var(--accent);text-decoration:none;font-weight:700}
.filterbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:16px}
.filterchip{display:inline-flex;align-items:center;gap:6px;padding:7px 13px;border-radius:13px;
  border:1px solid var(--border);background:var(--panel);color:var(--muted);font-size:12.5px;
  font-weight:700;text-decoration:none}
.filterchip .chipnum{font-size:13px;font-weight:800;color:var(--text)}
.filterchip.active{border-color:var(--item-accent,var(--accent));box-shadow:var(--shadow);color:var(--text)}
.filterchip.active .chipnum{color:var(--item-accent,var(--accent))}
.filterchip[data-fb="topics"]{--item-accent:var(--c-topics)}
.filterchip[data-fb="scripts"]{--item-accent:var(--c-scripts)}
.filter-context{display:inline-flex;align-items:center;gap:6px;padding:7px 13px;border-radius:13px;
  background:var(--accent-bg);color:var(--accent);font-size:12.5px;font-weight:700}
.filter-context a{color:inherit;text-decoration:none;opacity:.75}
.filter-context a:hover{opacity:1}
"""


def _esc(v) -> str:
    return html.escape(str(v), quote=True)


# ------------------------------------------------------------ 侧栏

_PAGES = [
    ("topics", "选题清单"),
    ("scripts", "脚本质检"),
    ("rundown", "排播表"),
    ("", "总览 · 体检与红线"),
]

RUNDOWN_DEFAULT_DAYS = 21


def _pending_topics(topics: list[Topic]) -> int:
    return sum(1 for t in topics if topics_mod.screen(t))


def _script_path(channel_id: str, air_date: date, program_id: str) -> Path:
    return SCRIPT_DIR / f"{channel_id}_{air_date}_{program_id}.json"


def _qc_status(ch: Channel, s: Script) -> tuple[str, str, list]:
    """返回 (tag_cls, tag_txt, active_findings)。active 排除已忽略的 warn。"""
    findings = qc_rules.run(s, ch)
    active = [f for f in findings if f.rule not in s.waived_rules]
    errors = [f for f in active if f.severity == "error"]
    warns = [f for f in active if f.severity == "warn"]
    if errors:
        return "tag-alarm", f"{len(errors)} 个错误", findings
    if warns:
        return "tag-warn", f"{len(warns)} 个警告", findings
    return "tag-ok", "全部通过", findings


def _pending_scripts(ch: Channel) -> int:
    n = 0
    for p in sorted(SCRIPT_DIR.glob(f"{ch.id}_*.json")):
        try:
            s = script_mod.load(p)
        except Exception:
            continue
        _, _, findings = _qc_status(ch, s)
        active = [f for f in findings if f.rule not in s.waived_rules]
        if active:
            n += 1
    return n


def _pending_rundown(ch: Channel, topics: list[Topic]) -> int:
    """接下来 RUNDOWN_DEFAULT_DAYS 天里,该配选题但还没配的天数。"""
    n = 0
    for a in rundown(ch, date.today(), RUNDOWN_DEFAULT_DAYS):
        if a.slot.mode not in ("fixed", "rotate") or not a.program:
            continue
        has_topic = any(t.air_date == a.air_date and t.program == a.program.id for t in topics)
        if not has_topic:
            n += 1
    return n


def _sidebar(channel_id: str, page: str, topics: list[Topic], ch: Channel) -> str:
    opts = []
    for c in list_channels():
        target = f"/{c}/{page}" if page else f"/{c}"
        selected = "selected" if c == channel_id else ""
        opts.append(f'<option value="{target}" {selected}>{_esc(load_channel(c).name)}</option>')
    channel_select = (
        '<select class="chswitch-select" onchange="location.href=this.value">'
        f'{"".join(opts)}</select>'
    )
    labels = {key: label for key, label in _PAGES}
    counts = {
        "topics": _pending_topics(topics),
        "scripts": _pending_scripts(ch),
        "rundown": _pending_rundown(ch, topics),
        "": None,
    }
    group1 = []
    for key in ("topics", "scripts", "rundown"):
        active = "active" if page == key else ""
        n = counts[key]
        cls = "navcount" + ("" if n else " zero")
        group1.append(
            f'<a class="navitem {active}" data-key="{key}" href="/{channel_id}/{key}">'
            f'<span>{_esc(labels[key])}</span>'
            f'<span class="{cls}">{n}</span></a>'
        )
    group2 = [
        f'<a class="navitem {"active" if page == "" else ""}" data-key="" href="/{channel_id}">'
        f'{_esc(labels[""])}</a>'
    ]
    return f"""<aside>
  <div class="brand">
    <div class="brand-badge">{_esc(ch.name[:2])}</div>
    <div>
      <div class="brand-name">{_esc(ch.name)}</div>
      <div class="brand-sub">内容工作台</div>
    </div>
  </div>
  <div class="chswitch">{channel_select}</div>
  <div class="navgroup">{''.join(group1)}</div>
  <div class="navgroup">{''.join(group2)}</div>
</aside>"""


def _shell(channel_id: str, page: str, title: str, sub: str, body: str) -> str:
    ch = load_channel(channel_id)
    topics = topics_mod.load_topics(channel_id)
    return f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>工作台 · {_esc(ch.name)}</title>
<style>{CSS}</style>
</head><body>
<div class="shell">
{_sidebar(channel_id, page, topics, ch)}
<main>
  <h1>{_esc(title)}</h1>
  <p class="pagesub">{_esc(sub)}</p>
  {body}
</main>
</div>
<footer class="muted">数据每次刷新都重新读盘 —— 操作即写回 data/*.json,不额外存状态。</footer>
</body></html>"""


# ------------------------------------------------------------ 总览页


def _health_section(channel_id: str, ch: Channel, topics: list[Topic]) -> str:
    rows = topics_mod.health(ch, topics)
    if not rows:
        return "<div class='empty'>这个频道还没有配置消耗节目。</div>"
    cards = []
    for r in rows:
        pct = 100.0 if r.weeks_left == float("inf") else min(r.weeks_left / 40 * 100, 100)
        bar_cls = "bar-alarm" if r.alarm else "bar-ok"
        left = "∞" if r.weeks_left == float("inf") else f"{r.weeks_left:.0f}"
        tag_cls, tag_txt = ("tag-alarm", "报警") if r.alarm else ("tag-ok", "正常")
        reasons = "、".join(r.reasons) if r.reasons else "储量健康,先不用管"
        cards.append(
            f"""<div class="statcard">
      <div class="statcard-head"><span class="statcard-title">
        <a href="/{channel_id}/topics?program={_esc(r.program)}" title="查看这档节目的选题">{_esc(r.name)}</a></span>
        <span class="tag {tag_cls}">{tag_txt}</span></div>
      <div class="statcard-num">{r.available}<small> / {r.target} 条储量 · 年耗 {r.per_year:.0f}</small></div>
      <div><div class="bar-track"><div class="bar-fill {bar_cls}" style="width:{pct:.0f}%"></div></div>
        剩 {left} 周</div>
      <div class="statcard-reason">{_esc(reasons)}</div>
    </div>"""
        )
    return f"<div class='cardgrid'>{''.join(cards)}</div>"


def _announce_text(channel_id: str, ch: Channel, a) -> tuple[str, bool]:
    """开场白展示文本,返回 (文本, 是否来自真实脚本)。

    开场白现在是每期手写的多主持人对话(见 script.skeleton 里的注释),不再是
    频道模板套出来的固定句子 —— 已经有脚本的日子必须读脚本里真实写的那几句,
    模板值只用来给还没写脚本的日子做占位预览,两者绝不能混着展示成一回事。
    """
    if a.program:
        path = _script_path(channel_id, a.air_date, a.program.id)
        if path.is_file():
            try:
                s = script_mod.load(path)
            except Exception:
                s = None
            if s is not None:
                lines = []
                for seg in s.segments:
                    if seg.kind != "announce":
                        if lines:
                            break
                        continue
                    if not seg.text.strip():
                        continue
                    speaker = ch.hosts.get(seg.voice, {}).get("name") if seg.voice else None
                    lines.append(f"{speaker}:{seg.text}" if speaker else seg.text)
                if lines:
                    return " ".join(lines), True
    return open_line(ch, a), False


def _rundown_section(channel_id: str, ch: Channel) -> str:
    airs = rundown(ch, date.today(), 14)
    if not airs:
        return "<div class='empty'>接下来 14 天没有排播。</div>"
    body = []
    for a in airs:
        name = a.program.name if a.program else a.slot.domain
        text, is_real = _announce_text(channel_id, ch, a)
        cell = _esc(text)
        if not is_real:
            cell += " <span class='tag tag-status'>模板占位</span>"
        body.append(
            f"<tr><td>{a.air_date}</td><td>{_esc(ch.weekday_names[a.weekday - 1])}</td>"
            f"<td>{_esc(name)}</td><td>{cell}</td></tr>"
        )
    return (
        "<table><thead><tr><th>日期</th><th>星期</th><th>节目</th><th>开场白</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def page_overview(channel_id: str) -> str:
    ch = load_channel(channel_id)
    topics = topics_mod.load_topics(channel_id)
    body = f"""
  <section><h2>选题池体检</h2>{_health_section(channel_id, ch, topics)}</section>
  <section><h2>未来 14 天排播 <a href="/{channel_id}/rundown">→ 去排播表指定选题 / 生成骨架</a></h2>
    {_rundown_section(channel_id, ch)}</section>
  <section><h2>红线参考</h2>
    <table><tbody>{''.join(f"<tr><td>{_esc(r)}</td></tr>" for r in ch.redlines)}</tbody></table>
  </section>
"""
    return _shell(channel_id, "", "总览", "选题池储量、红线参考 —— 只读", body)


# ------------------------------------------------------------ 选题清单页


def _topic_row(t: Topic) -> str:
    probs = topics_mod.screen(t)
    tag_cls, tag_txt = ("tag-ok", "通过") if not probs else ("tag-warn", "待补")
    reason = "; ".join(probs) if probs else "—"
    nxt = topics_mod.next_status(t.status)
    actions = []
    if nxt:
        actions.append(
            f'<form class="inline" method="post" action="/{t.channel}/topics/status">'
            f'<input type="hidden" name="id" value="{_esc(t.id)}">'
            f'<input type="hidden" name="status" value="{_esc(nxt)}">'
            f'<button class="primary" type="submit">推进→{_esc(nxt)}</button></form>'
        )
    if t.status not in ("aired", "killed"):
        actions.append(
            f'<form class="inline" method="post" action="/{t.channel}/topics/status">'
            f'<input type="hidden" name="id" value="{_esc(t.id)}">'
            f'<input type="hidden" name="status" value="killed">'
            f'<button class="danger" type="submit">淘汰</button></form>'
        )
    edit_form = f"""<details><summary>编辑</summary>
    <form class="editform" method="post" action="/{t.channel}/topics/edit">
      <input type="hidden" name="id" value="{_esc(t.id)}">
      <label>标题</label><input name="title" value="{_esc(t.title)}">
      <label>转述句(≤40字)</label><input name="retell" value="{_esc(t.retell)}">
      <label>翻转句</label><input name="flip" value="{_esc(t.flip)}">
      <label>演示(demo)</label><input name="demo" value="{_esc(t.demo)}">
      <label>音频素材(asset)</label>
      <select name="asset">
        {''.join(f'<option value="{v}" {"selected" if t.asset == v else ""}>{v}</option>' for v in ("none", "synth", "archive"))}
      </select>
      <button class="primary" type="submit">保存</button>
    </form></details>"""
    return (
        f"<tr><td><code>{_esc(t.id)}</code></td>"
        f"<td>{_esc(t.program)} / {_esc(t.category)}</td>"
        f"<td>{_esc(t.title)}</td>"
        f"<td><span class='tag tag-status'>{_esc(t.status)}</span></td>"
        f"<td><span class='tag {tag_cls}'>{tag_txt}</span></td>"
        f"<td class='muted'>{_esc(reason)}</td>"
        f"<td><div class='actions'>{''.join(actions)}</div>{edit_form}</td></tr>"
    )


_STATUS_ORDER = ["pool", "picked", "verified", "written", "aired", "killed"]
_STATUS_LABELS = {
    "pool": "选题池", "picked": "已选中", "verified": "已核实",
    "written": "已写稿", "aired": "已播出", "killed": "已淘汰",
}


def _topics_filter_bar(channel_id: str, ch: Channel, scoped: list[Topic], status: str | None, program: str | None) -> str:
    def chip(label: str, key: str | None, count: int) -> str:
        active = "active" if status == key else ""
        qp = ([f"status={key}"] if key else []) + ([f"program={_esc(program)}"] if program else [])
        href = f"/{channel_id}/topics" + (("?" + "&".join(qp)) if qp else "")
        return f'<a class="filterchip {active}" data-fb="topics" href="{href}">{label} <span class="chipnum">{count}</span></a>'

    chips = [chip("全部", None, len(scoped))]
    chips += [chip(_STATUS_LABELS[s], s, sum(1 for t in scoped if t.status == s)) for s in _STATUS_ORDER]
    bar = f"<div class='filterbar'>{''.join(chips)}"
    if program:
        name = next((p.name for p in ch.programs if p.id == program), program)
        clear = f"/{channel_id}/topics" + (f"?status={status}" if status else "")
        bar += f"<span class='filter-context'>只看:{_esc(name)} <a href='{clear}'>清除</a></span>"
    return bar + "</div>"


def page_topics(channel_id: str, status: str | None = None, program: str | None = None) -> str:
    ch = load_channel(channel_id)
    all_topics = topics_mod.load_topics(channel_id)
    if not all_topics:
        body = "<div class='empty'>选题池是空的,先去补几条选题吧。</div>"
    else:
        scoped = [t for t in all_topics if not program or t.program == program]
        shown = [t for t in scoped if not status or t.status == status]
        filterbar = _topics_filter_bar(channel_id, ch, scoped, status, program)
        if not shown:
            body = filterbar + "<div class='empty'>这个筛选条件下没有选题。</div>"
        else:
            ordered = sorted(shown, key=lambda t: _STATUS_ORDER.index(t.status) if t.status in _STATUS_ORDER else 99)
            rows = "".join(_topic_row(t) for t in ordered)
            table = (
                "<table><thead><tr><th>id</th><th>节目/类目</th><th>标题</th>"
                "<th>状态</th><th>准入</th><th>问题</th><th>操作</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>"
            )
            body = filterbar + table
    return _shell(
        channel_id, "topics", "选题清单",
        "推进状态、淘汰、或直接补全「待补」的字段 —— 保存后自动重新过三关测试",
        f"<section>{body}</section>",
    )


# ------------------------------------------------------------ 脚本质检页


def _finding_row(script_path: Path, s: Script, f) -> str:
    waived = f.rule in s.waived_rules
    cls = "waived" if waived else ""
    action = ""
    if f.severity == "warn":
        op = "unwaive" if waived else "waive"
        label = "取消忽略" if waived else "忽略"
        action = (
            f'<form class="inline" method="post" action="/{s.channel}/scripts/waive">'
            f'<input type="hidden" name="file" value="{_esc(script_path.name)}">'
            f'<input type="hidden" name="rule" value="{_esc(f.rule)}">'
            f'<input type="hidden" name="op" value="{op}">'
            f'<button class="warn" type="submit">{label}</button></form>'
        )
    sev_cls = "tag-alarm" if f.severity == "error" else "tag-warn"
    return (
        f"<div class='finding-row {cls}'>"
        f"<span><span class='tag {sev_cls}'>{f.severity}</span> {_esc(f.rule)}: {_esc(f.message)}"
        f"{' <span class=\"muted\">(已忽略)</span>' if waived else ''}</span>{action}</div>"
    )


def _segment_editor(script_path: Path, s: Script) -> str:
    cards = []
    for i, seg in enumerate(s.segments):
        if seg.kind in ("sting", "sfx", "silence"):
            cards.append(
                f"""<div class="segcard">
      <div class="segcard-head"><span class="segcard-idx">{i}</span>{_esc(seg.kind)}
        <span>· {seg.est_seconds}s</span></div>
      <div class="segcard-fixed">{_esc(seg.asset or '固定素材,无文本')}</div>
    </div>"""
            )
            continue
        cards.append(
            f"""<div class="segcard">
      <div class="segcard-head"><span class="segcard-idx">{i}</span>{_esc(seg.kind)}</div>
      <form method="post" action="/{s.channel}/scripts/segment">
        <input type="hidden" name="file" value="{_esc(script_path.name)}">
        <input type="hidden" name="index" value="{i}">
        <textarea name="text">{_esc(seg.text)}</textarea>
        <button class="primary" type="submit">保存</button>
      </form>
    </div>"""
        )
    return f"<div class='seclist'>{''.join(cards)}</div>"


_SCRIPT_FILTER_LABELS = [("alarm", "有错误"), ("warn", "有警告"), ("ok", "全部通过")]


def page_scripts(channel_id: str, status: str | None = None) -> str:
    ch = load_channel(channel_id)
    paths = sorted(SCRIPT_DIR.glob(f"{ch.id}_*.json"))
    error_blocks, loaded = [], []
    for p in paths:
        try:
            s = script_mod.load(p)
        except Exception as e:  # noqa: BLE001 - 展示给用户看
            error_blocks.append(f"<section><h2>{_esc(p.name)}</h2><p class='muted'>读取失败:{_esc(e)}</p></section>")
            continue
        tag_cls, tag_txt, findings = _qc_status(ch, s)
        key = {"tag-ok": "ok", "tag-warn": "warn", "tag-alarm": "alarm"}[tag_cls]
        loaded.append((p, s, tag_cls, tag_txt, findings, key))

    if not paths:
        body = "<div class='empty'>还没有脚本,先去排播表生成一个骨架吧。</div>"
    else:
        def chip(label: str, key: str | None, count: int) -> str:
            active = "active" if status == key else ""
            href = f"/{channel_id}/scripts" + (f"?status={key}" if key else "")
            return f'<a class="filterchip {active}" data-fb="scripts" href="{href}">{label} <span class="chipnum">{count}</span></a>'

        chips = [chip("全部", None, len(loaded))]
        chips += [chip(label, key, sum(1 for row in loaded if row[5] == key)) for key, label in _SCRIPT_FILTER_LABELS]
        filterbar = f"<div class='filterbar'>{''.join(chips)}</div>"

        shown = [row for row in loaded if not status or row[5] == status]
        blocks = list(error_blocks) if not status else []
        for p, s, tag_cls, tag_txt, findings, _key in shown:
            findings_html = "".join(_finding_row(p, s, f) for f in findings) or "<p class='muted'>无质检项。</p>"
            blocks.append(
                f"""<section>
  <h2><code>{_esc(p.name)}</code> · {_esc(s.program)} · {s.air_date}
    <span class="tag {tag_cls}">{tag_txt}</span></h2>
  <p class="muted">{s.duration_s:.0f}s / {s.word_count} 字</p>
  <details open><summary>质检详情</summary>{findings_html}</details>
  <details><summary>编辑文本</summary>{_segment_editor(p, s)}</details>
</section>"""
            )
        if not shown and not blocks:
            blocks.append("<div class='empty'>这个筛选条件下没有脚本。</div>")
        body = filterbar + "".join(blocks)
    return _shell(
        channel_id, "scripts", "脚本质检",
        "error 级别必须改文本才能消掉;warn 级别人工复核后可以标记忽略",
        body,
    )


# ------------------------------------------------------------ 排播表页


def _content_status(ch: Channel, channel_id: str, a, topics: list[Topic]) -> tuple[str, str]:
    """当天内容状态。这是给未来真实生成流程预留的位置 —— 现在只读脚本文件
    是否存在、质检是否通过来判断,不编造"生成中"这种假状态。"""
    if not a.program:
        return "tag-status", "—"
    if a.slot.mode not in ("fixed", "rotate"):
        return "tag-status", "重播 · 不占选题池"
    path = _script_path(channel_id, a.air_date, a.program.id)
    if path.is_file():
        try:
            s = script_mod.load(path)
        except Exception:
            return "tag-alarm", "脚本读取失败"
        tag_cls, tag_txt, _ = _qc_status(ch, s)
        return tag_cls, tag_txt
    has_topic = any(t.air_date == a.air_date and t.program == a.program.id for t in topics)
    if has_topic:
        return "tag-warn", "已选题 · 待生成骨架"
    return "tag-alarm", "未排期"


def _rundown_row(ch: Channel, channel_id: str, a, topics: list[Topic]) -> str:
    name = a.program.name if a.program else a.slot.domain
    tag_cls, tag_txt = _content_status(ch, channel_id, a, topics)
    actions = "<span class='muted'>—</span>"
    assigned_title = "—"
    if a.program and a.slot.mode in ("fixed", "rotate"):
        assigned = next(
            (t for t in topics if t.air_date == a.air_date and t.program == a.program.id), None
        )
        has_script = _script_path(channel_id, a.air_date, a.program.id).is_file()
        if assigned:
            assigned_title = _esc(assigned.title)
        if has_script:
            actions = f'<a class="btn" href="/{channel_id}/scripts">去脚本质检 →</a>'
        else:
            cands = [
                t for t in topics
                if t.program == a.program.id and t.status in ("pool", "picked", "verified")
            ]
            cands.sort(key=lambda t: len(topics_mod.screen(t)))
            options = "".join(
                f'<option value="{_esc(t.id)}" {"selected" if assigned and t.id == assigned.id else ""}>'
                f'{_esc(t.id)} · {_esc(t.title[:18])}</option>'
                for t in cands
            )
            assign_form = f"""<form class="assign-form inline" method="post" action="/{channel_id}/rundown/assign">
        <input type="hidden" name="date" value="{a.air_date}">
        <input type="hidden" name="program" value="{a.program.id}">
        <select name="topic_id"><option value="">-- 选选题 --</option>{options}</select>
        <button class="primary" type="submit">指定</button>
      </form>"""
            gen_form = ""
            if assigned:
                gen_form = f"""<form class="inline" method="post" action="/{channel_id}/rundown/generate">
        <input type="hidden" name="date" value="{a.air_date}">
        <input type="hidden" name="program" value="{a.program.id}">
        <button class="primary" type="submit">生成骨架</button>
      </form>
      <form class="inline" method="post" action="/{channel_id}/rundown/unassign">
        <input type="hidden" name="date" value="{a.air_date}">
        <input type="hidden" name="program" value="{a.program.id}">
        <button type="submit">取消指定</button>
      </form>"""
            actions = f"<div class='actions'>{assign_form}{gen_form}</div>"
    return (
        f"<tr><td>{a.air_date}</td><td>{_esc(ch.weekday_names[a.weekday - 1])}</td>"
        f"<td>{_esc(name)}</td>"
        f"<td class='muted'>{assigned_title}</td>"
        f"<td><span class='tag {tag_cls}'>{_esc(tag_txt)}</span></td>"
        f"<td>{actions}</td></tr>"
    )


def page_rundown(channel_id: str, start: date | None = None, days: int = RUNDOWN_DEFAULT_DAYS) -> str:
    ch = load_channel(channel_id)
    topics = topics_mod.load_topics(channel_id)
    start = start or date.today()
    airs = rundown(ch, start, days)
    if not airs:
        body = "<div class='empty'>这个区间没有排播。</div>"
    else:
        rows = "".join(_rundown_row(ch, channel_id, a, topics) for a in airs)
        body = (
            "<table><thead><tr><th>日期</th><th>星期</th><th>节目</th>"
            "<th>已指定选题</th><th>内容状态</th><th>操作</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    prev_start = start - timedelta(days=days)
    next_start = start + timedelta(days=days)
    rangebar = (
        f"<div class='rangebar'>"
        f"<a href='/{channel_id}/rundown?start={prev_start}&days={days}'>← 前 {days} 天</a>"
        f"<span class='muted'>{start} 起 {days} 天</span>"
        f"<a href='/{channel_id}/rundown?start={next_start}&days={days}'>后 {days} 天 →</a>"
        f"<form class='inline' method='post' action='/{channel_id}/rundown/autoassign'>"
        f"<input type='hidden' name='start' value='{start}'>"
        f"<input type='hidden' name='days' value='{days}'>"
        f"<button class='primary' type='submit'"
        f" title='对这段区间里还没指定选题的日子,按&quot;不撞最近类目 + 越准备好越优先&quot;自动挑一条'>"
        f"自动排播未指定的日子</button></form>"
        f"</div>"
    )
    return _shell(
        channel_id, "rundown", "排播表",
        "指定选题落到具体播出日、一键生成脚本骨架。“内容状态”读的是脚本文件是否存在/质检结果,"
        "不是假的生成中状态 —— 以后接入真实生成流程时,这一列直接切换成那边的真实进度",
        rangebar + body,
    )


# ------------------------------------------------------------ 写操作


def _load_script_or_404(channel_id: str, filename: str) -> tuple[Path, Script] | None:
    if not filename.startswith(f"{channel_id}_") or "/" in filename or "\\" in filename:
        return None
    path = SCRIPT_DIR / filename
    if not path.is_file():
        return None
    return path, script_mod.load(path)


def act_topic_status(channel_id: str, form: dict) -> bool:
    topics = topics_mod.load_topics(channel_id)
    tid, status = form.get("id"), form.get("status")
    t = next((x for x in topics if x.id == tid), None)
    if t is None or status not in (*topics_mod.STATUS_FLOW, "killed"):
        return False
    t.status = status  # type: ignore[assignment]
    topics_mod.save_topics(channel_id, topics)
    return True


def act_topic_edit(channel_id: str, form: dict) -> bool:
    topics = topics_mod.load_topics(channel_id)
    tid = form.get("id")
    t = next((x for x in topics if x.id == tid), None)
    if t is None:
        return False
    for field in ("title", "retell", "flip", "demo"):
        if field in form:
            setattr(t, field, form[field])
    if form.get("asset") in ("none", "synth", "archive"):
        t.asset = form["asset"]  # type: ignore[assignment]
    topics_mod.save_topics(channel_id, topics)
    return True


def act_script_waive(channel_id: str, form: dict) -> bool:
    loaded = _load_script_or_404(channel_id, form.get("file", ""))
    if loaded is None:
        return False
    path, s = loaded
    rule, op = form.get("rule"), form.get("op")
    if op == "waive" and rule not in s.waived_rules:
        s.waived_rules.append(rule)
    elif op == "unwaive" and rule in s.waived_rules:
        s.waived_rules.remove(rule)
    path.write_text(s.model_dump_json(indent=2), encoding="utf-8")
    return True


def act_script_segment(channel_id: str, form: dict) -> bool:
    loaded = _load_script_or_404(channel_id, form.get("file", ""))
    if loaded is None:
        return False
    path, s = loaded
    try:
        idx = int(form.get("index", "-1"))
    except ValueError:
        return False
    if not (0 <= idx < len(s.segments)):
        return False
    s.segments[idx].text = form.get("text", "")
    path.write_text(s.model_dump_json(indent=2), encoding="utf-8")
    return True


def act_rundown_assign(channel_id: str, form: dict) -> bool:
    try:
        d = date.fromisoformat(form.get("date", ""))
    except ValueError:
        return False
    program_id = form.get("program", "")
    topics = topics_mod.load_topics(channel_id)
    t = next((x for x in topics if x.id == form.get("topic_id")), None)
    if t is None or t.program != program_id:
        return False
    for other in topics:
        if other is not t and other.air_date == d and other.program == program_id:
            other.air_date = None
    t.air_date = d
    topics_mod.save_topics(channel_id, topics)
    return True


def act_rundown_unassign(channel_id: str, form: dict) -> bool:
    try:
        d = date.fromisoformat(form.get("date", ""))
    except ValueError:
        return False
    program_id = form.get("program", "")
    topics = topics_mod.load_topics(channel_id)
    t = next((x for x in topics if x.air_date == d and x.program == program_id), None)
    if t is None:
        return False
    t.air_date = None
    topics_mod.save_topics(channel_id, topics)
    return True


def act_rundown_generate(channel_id: str, form: dict) -> bool:
    try:
        d = date.fromisoformat(form.get("date", ""))
    except ValueError:
        return False
    ch = load_channel(channel_id)
    air = resolve(ch, d)
    if air is None or air.program is None:
        return False
    topics = topics_mod.load_topics(channel_id)
    t = next((x for x in topics if x.air_date == d and x.program == air.program.id), None)
    if t is None:
        return False
    s = script_mod.skeleton(ch, air, t)
    script_mod.save(s)
    return True


def act_rundown_autoassign(channel_id: str, form: dict) -> bool:
    """把这段区间里"该有选题但还没指定"的日子,自动挑一条钉上去。

    调用 topics_mod.pick(),同一批里前面刚指定的日子会立刻计入"最近类目",
    所以批量跑的时候,后面的日子也躲得开前面刚选过的类目 —— 不用分开跑
    好几次才生效。
    """
    ch = load_channel(channel_id)
    try:
        start = date.fromisoformat(form["start"]) if form.get("start") else date.today()
        days = int(form.get("days") or RUNDOWN_DEFAULT_DAYS)
    except ValueError:
        return False
    topics = topics_mod.load_topics(channel_id)
    changed = False
    for a in rundown(ch, start, days):
        if not a.program or a.slot.mode not in ("fixed", "rotate"):
            continue
        if any(t.air_date == a.air_date and t.program == a.program.id for t in topics):
            continue
        cands = topics_mod.pick(topics, a.program.id, n=1)
        if not cands:
            continue
        cands[0].air_date = a.air_date
        changed = True
    if changed:
        topics_mod.save_topics(channel_id, topics)
    return True


_ACTIONS = {
    ("topics", "status"): act_topic_status,
    ("topics", "edit"): act_topic_edit,
    ("scripts", "waive"): act_script_waive,
    ("scripts", "segment"): act_script_segment,
    ("rundown", "assign"): act_rundown_assign,
    ("rundown", "unassign"): act_rundown_unassign,
    ("rundown", "generate"): act_rundown_generate,
    ("rundown", "autoassign"): act_rundown_autoassign,
}


# ------------------------------------------------------------ HTTP


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 静默,别刷屏控制台
        pass

    def do_GET(self):
        url = urlparse(self.path)
        parts = url.path.strip("/").split("/")
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        channels = list_channels()
        if not channels:
            self._send(500, "没有找到任何频道配置(channels/*.yaml)")
            return
        channel_id = parts[0] or channels[0]
        if channel_id not in channels:
            self._send(404, f"找不到频道 {channel_id}")
            return
        page = parts[1] if len(parts) > 1 and parts[1] else ""
        try:
            if page == "topics":
                body = page_topics(channel_id, query.get("status"), query.get("program"))
            elif page == "scripts":
                body = page_scripts(channel_id, query.get("status"))
            elif page == "rundown":
                start = date.fromisoformat(query["start"]) if query.get("start") else None
                days = int(query["days"]) if query.get("days") else RUNDOWN_DEFAULT_DAYS
                body = page_rundown(channel_id, start, days)
            elif page == "":
                body = page_overview(channel_id)
            else:
                self._send(404, f"找不到页面 {page}")
                return
        except Exception as e:  # noqa: BLE001 - 渲染错误直接显示给用户
            self._send(500, f"渲染失败:{e}")
            return
        self._send(200, body)

    def do_POST(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        channels = list_channels()
        if len(parts) != 3 or parts[0] not in channels:
            self._send(404, "找不到该操作")
            return
        channel_id, page, action = parts
        fn = _ACTIONS.get((page, action))
        if fn is None:
            self._send(404, "找不到该操作")
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        form = {k: v[0] for k, v in parse_qs(raw).items()}
        try:
            ok = fn(channel_id, form)
        except Exception as e:  # noqa: BLE001 - 操作失败直接显示给用户
            self._send(500, f"操作失败:{e}")
            return
        if not ok:
            self._send(400, "操作失败:参数不对或对象不存在")
            return
        self.send_response(303)
        self.send_header("Location", f"/{channel_id}/{page}")
        self.end_headers()

    def _send(self, code: int, body: str):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(channel: str | None = None, port: int = 8765, open_browser: bool = True):
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{port}/{channel or ''}"
    print(f"工作台已启动:{url}  (Ctrl+C 停止)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
