# radio_factory

儿童音频电台内容工厂。

**核心设计:频道是配置,不是代码。**
新增一个方向(动植物、身体、地球)= 写一个 `channels/*.yaml`,不改一行 Python。
仓库里已经放了两个频道来验证这一点:`space`(小小航天队)和 `nature`(小小观察队)。

---

## 快速开始

```bash
pip install -e .

rf channels                              # 列出频道
rf rundown space --start 2026-09-07 --days 21   # 三周排播表
rf today space                           # 今天播什么
rf stings space                          # 合成声音标识 wav
rf skeleton space 2026-09-08 --topic-id lab-001 # 生成脚本骨架
rf check space data/scripts/xxx.json     # 跑质检
rf voices                                # 核对 MiniMax 账号里真实的音色列表
rf synthesize space data/scripts/xxx.json # 调 MiniMax 把脚本逐段合成 mp3
rf screen space                          # 选题准入检查
rf health space                          # 选题池体检
rf dashboard space                       # 本地工作台:体检 + 质检 + 排播,支持推进选题/改文本/忽略警告
```

---

## 这个仓库负责什么

| 层 | 在不在这里 | 说明 |
|---|---|---|
| 频道定义 | ✅ | 节目、时段、轮换、锚点、结构骨架 |
| 排播引擎 | ✅ | 给日期算出播什么,含三周轮换 |
| 选题池 | ✅ | 准入筛选 + 储量体检 |
| 脚本结构 | ✅ | 结构化 Segment,音效点位写在脚本里 |
| 质检 | ✅ | 数据驱动,规则写在 YAML |
| 声音标识 | ✅ | numpy 合成,零素材依赖 |
| **文案生成** | ❌ | 提示词等脚本格式定稿再做 |
| **TTS 合成(单段)** | ✅ | `rf synthesize` 调 MiniMax,把脚本逐段合成 mp3,音色映射见 [voices.yaml](voices.yaml) |
| **音频拼接 / 混音** | ❌ | 你已有 ffmpeg 链路,保持解耦——单段音频拿到之后怎么拼成一整期、怎么混,不在这里做 |

**文案生成、混音仍然刻意不做。** 生成和混音耦合进来会让这个框架绑死在一个频道上,
而框架的价值恰恰是跨频道复用。**TTS 这一条边界松动过一次**——从"只导出任务描述"
变成"能实际调用 MiniMax 把单段文字合成音频",但止步于单段,没有往拼接/混音方向
继续扩张。

---

## 目录

```
channels/          频道配置 —— 扩展点在这里
  space.yaml       小小航天队
  nature.yaml      小小观察队(示例,证明可扩展)
src/radio_factory/
  models.py        数据模型:Channel / Slot / Program / Topic / Script
  schedule.py      排播引擎
  topics.py        选题池:准入筛选 + 储量体检
  script.py        脚本骨架 + TTS 任务导出
  qc/rules.py      质检规则注册表
  audio/stings.py  声音标识合成
  cli.py           命令行
data/topics/       选题池 JSON
data/scripts/      脚本 JSON
out/               合成产物
```

---

## 怎么加一个新频道

写一个 `channels/xxx.yaml`,填五块:

1. **基本信息** —— `id` / `name` / `open_line` / `epoch`(必须是周一)
2. **structure** —— 节目固定骨架。不同频道可以不一样,
   比如 `nature` 比 `space` 多一步"模仿一下"(动物动作能用身体做,航天不行)
3. **stings** —— 每天的声音标识,`kind` 从
   `sweep / bells / noise / ambient / metal / pulse / chime` 里选
4. **slots** —— 一周七格必须写全。`mode` 四选一:
   - `fixed` 固定档,只能挂 1 档节目
   - `rotate` 轮换档,至少 2 档,每周前进一档
   - `recap` 重播档,不消耗选题池
   - `"off"` 留空 —— **注意必须加引号**,YAML 会把裸写的 `off` 解析成 `False`
5. **qc / redlines** —— 质检规则和红线

需要频道特有的新规则时,在 `qc/rules.py` 加一个 `@register("规则名")` 函数,
别处不用改。`no_anthropomorphism`(禁拟人化)和 `no_contact`(禁接触引导)
就是这么给动植物频道加的。

---

## 两条硬约定

**孩子看不到节目表,预期感只能靠耳朵建立。**

三层锚点在配置里是强制项:

- `slot.announce` 领域宣告,一年不变。轮换只能改节目的 `tagline`(后半句)
- `slot.sting` 每天固定的 3 秒声音标识
- 每期结尾必须有 `preview` 段落,由 `require_segment` 规则强制

`test_announce_is_stable_anchor` 会守住第一条。

**提示词写得再好也不够,必须生成后自动检查。**

质检规则是数据,不是散落在提示词里的叮嘱。`space` 12 条,`nature` 11 条,
其中 `honesty_flag`(声化数据必须声明是翻译过来的)是内容诚实性的地基,
`audio_safety`(高频演示不超过 5 秒)是听力安全的硬约束。

---

## 已知不足

- `number_anchor` 规则只认阿拉伯数字,中文数字("六秒""一亿")抓不到
- `Segment.est_seconds` 用 4.2 字/秒估算,真实时长要等 TTS 出来才准;
  建议合成后回写实测时长再跑一次 `duration` 检查
- 选题池是 JSON 单文件,几百条够用,上千条要换 SQLite
- 季播制(每季换 1–2 档)还没进模型,现在换节目要手改 YAML

---

## 测试

```bash
python -m pytest tests -q
```

12 个用例,覆盖:配置加载、周日留空、三周轮换回环、固定档不变、
锚点稳定性、质检各规则、频道特有规则、选题准入。
