# 交接文档

写给下一个完全没有上下文的会话看的。先读这份,再读 [README.md](README.md)(项目说明)和 [PROMPT.md](PROMPT.md)(文案生成 brief)。

---

## 这是个什么项目

`radio_factory`——儿童音频电台内容工厂。核心设计原则:**频道是配置,不是代码**。新增一个方向(动植物、身体、地球…)= 写一个 `channels/*.yaml`,不改 Python。现有两个频道验证这一点:`space`(小小航天队)、`nature`(小小观察队,选题池目前是空的)。

仓库**不是** git 仓库(`git status` 报 `fatal: not a git repository`)。没有版本控制,改错了没法 `git diff` 或回滚,动手前自己留意。

技术栈:Python + pydantic(数据模型)+ typer(CLI)+ 纯标准库 `http.server`(本地工作台,没用任何 web 框架)。虚拟环境在 `.venv/`,入口是 `.venv/Scripts/rf.exe`(Windows)。

---

## 这次会话在做什么任务

用户先问了"内容创作层要不要搞多套 AI 配置(人设/脚本/TTS/音乐,按频道不同)",我给了建议(沿用现有 `PROMPT.md` 的"通用规范 + 频道 override"两段式模式,新扩展 persona/TTS/music 三份姊妹文件)——**但这部分只讨论了,没有动手写**,见下面"下一步"。

用户接着转向了工作台(dashboard):从"只读展示"改成"能操作"。这是这次会话实际做的**全部代码工作**。

---

## 已经完成了什么

### 1. 工作台从只读变成可写(核心工作)

原来 `dashboard.py` 只有 `do_GET`,纯读盘展示。现在:

- **侧栏导航样式**:仿用户给的一张截图(左侧图标徽章 + 频道名 + 分组菜单,菜单项带"待处理"数字角标),替掉了原来的顶部 tab
- **拆成四个子页面**(原来是一个大长页):
  - `/{channel}` —— 总览(选题池体检 + 红线参考,只读)
  - `/{channel}/topics` —— 选题清单(可操作)
  - `/{channel}/scripts` —— 脚本质检(可操作)
  - `/{channel}/rundown` —— 排播表(新增,可操作)
- **写操作全部是 POST + 303 重定向回 GET**,直接改 `data/*.json`,没加数据库、没加内存状态。这是仓库原有的设计哲学("读盘即真相"),这次只是把它从"只读"扩展到"读写"。

具体能操作什么:

| 页面 | 能做的操作 | 对应的 POST 端点 |
|---|---|---|
| 选题清单 | 状态流转(pool→picked→verified→written→aired),淘汰(→killed) | `/{ch}/topics/status` |
| 选题清单 | 编辑"待补"选题的 title/retell/flip/demo/asset | `/{ch}/topics/edit` |
| 脚本质检 | 忽略 `warn` 级质检项(**`error` 级故意不给忽略按钮**——红线不能被点掉,必须真改文本) | `/{ch}/scripts/waive` |
| 脚本质检 | 直接编辑某个 segment 的文本,保存后立刻重新质检 | `/{ch}/scripts/segment` |
| 排播表 | 把选题池里的某条指定到具体播出日(写入 `Topic.air_date`——这个字段模型里一直有,之前没人用) | `/{ch}/rundown/assign` / `unassign` |
| 排播表 | 已指定选题的日子,一键生成脚本骨架(相当于点了个按钮版的 `rf skeleton`) | `/{ch}/rundown/generate` |

### 2. 数据模型改动

- [models.py](src/radio_factory/models.py):`Script` 新增字段 `waived_rules: list[str] = []`——记录人工复核后忽略的 warn 级规则 id,写进脚本 JSON 里持久化,不是内存状态
- [topics.py](src/radio_factory/topics.py):新增 `STATUS_FLOW` 常量和 `next_status()` 函数,给状态流转按钮用

### 3. 排播表页面里"内容状态"这一列是什么

用户问过"要不要显示 AI 在跑的状态"。**仓库里现在没有任何 AI/TTS 调用代码**(README 写得很明确:文案生成、TTS、混音都故意不做,保持解耦)。跟用户确认后的结论是:**先留位置,不编造假状态**。

现在这一列读的是真实数据:有没有对应的脚本文件、质检结果如何,标签是「未排期 / 已选题·待生成骨架 / N 个错误 / N 个警告 / 全部通过」。以后接入真正的生成流程时,直接把这一列换成那边的真实进度就行——**换的时候去改 `_content_status()` 这个函数**,在 [dashboard.py](src/radio_factory/dashboard.py) 里。

### 4. 已经端到端验证过的东西

用 `rf skeleton` 生成过测试脚本、走过 assign→generate→质检→忽略警告→改文本 全流程,确认读写链路都对。**测试完都清理干净了**——`data/scripts/` 现在是空的,`data/topics/space.json` 恢复成原始的 4 条 pool 状态选题,`data/topics/nature.json` 本来就不存在(nature 选题池是空的,这是真实状态不是我清出来的)。

---

## 当前卡在哪 / 没做完的事

**没有卡住,但有一件事没做**:上面提到的"内容创作 AI 配置"(persona/TTS/music 多套 prompt 规范)——用户提出这个话题后,对话转向了工作台可操作性,这部分还停在"讨论了方向,没写文件"的阶段。见下面"下一步"。

工作台本身功能上是完整的、验证过的,没有已知 bug。

---

## 下一步计划

1. **内容创作 AI 配置**(本次会话最初的诉求,还没动手):在 `PROMPT.md` 的"通用规范 + 频道特有 override"模式基础上,补三份姊妹文件/配置:
   - **persona**:通用主持人语气基线 + 频道 override
   - **TTS**:结构化 voice_profile,按 `segment.kind` 映射音色/语速/情绪,建议直接挂进 `channels/*.yaml`(参考现有 `stings` 字段的写法)
   - **music/BGM**:风格标签库,按 slot 或 program 绑定
   - **注意**:软调性(persona/TTS/music)不能有能力覆盖硬约束(`qc`/`redlines` 里的红线),这条边界要守住,别让"活泼人设"绕开安全线
2. **接真实生成流程**时,`dashboard.py` 里的 `_content_status()` 函数是唯一要改的地方,把"读脚本文件"换成"读真实生成状态"
3. `nature` 频道选题池是空的,如果要验证 nature 频道的排播表/工作台功能,得先往 `data/topics/nature.json` 里补几条选题(格式参考 `data/topics/space.json`)

---

## 踩过的坑,不要再踩

1. **Windows 终端是 GBK codepage,不是 UTF-8**。这个环境下两个后果:
   - `rich` 库 console.print 遇到 `✓` `✗` 这类字符会 `UnicodeEncodeError: 'gbk' codec can't encode`。这是**预先存在的 bug**,不是这次改动引入的——`rf skeleton` 等命令实际上文件已经存好了,只是最后那行 `console.print(f"✓ ...")` 崩了导致命令显示"失败"。**看到这个报错先去确认文件是不是已经写成功了,别慌**。这次会话没有修它,值得单独开一次会话专门处理(比如把 `✓`/`✗` 换成 ASCII 或者 catch 这个异常)。
   - **不要用 Bash 工具里的 `curl --data-urlencode` 传中文去测试 POST 接口**——Git Bash 在 GBK 终端下传参会把中文编码搞乱,服务端收到的是乱码(不是服务端 bug!)。测 UTF-8 POST 请求要用 `python -c "...urllib.request..."`,用 Python 里的字符串字面量,不经过命令行参数传递。这次会话用这个方法验证过 segment 编辑和 rundown assign/generate 接口,确认服务端逻辑是对的。
2. **这个环境下的浏览器自动化工具(Claude_Browser 的 `computer`/`form_input` + ref)点提交按钮不一定可靠**——测试时出现过"选了值、点了保存,页面刷新后数据没变"的情况,一开始以为是服务端 bug,后来直接用 Python `urllib` 打同一个 POST 端点验证,数据是对的、写盘成功了。**结论是自动化工具的 ref 点击在这个场景下不稳定,不是应用本身的 bug**。以后再验证工作台的写操作,优先用 `urllib` 直接打端点,浏览器自动化工具用来看页面渲染对不对就行,别太依赖它做交互测试。
3. **改完 `dashboard.py` 之后,后台跑着的旧服务进程不会自动重启**,得手动 `netstat -ano | grep 8765` 找 PID、`taskkill //PID <pid> //F` 杀掉,再重新 `rf dashboard <channel> --port 8765 --no-open` 起一个新的,不然测的还是改之前的代码。
4. **别用 `git` 相关命令**——这不是 git 仓库,`git status`/`git diff` 都会报错,想看改动只能自己对比或者问用户有没有其他备份手段。
5. **`data/scripts/` 和 `data/topics/*.json` 是用户的真实数据,不是测试夹具**。这次会话每次用真实 CLI/接口生成测试数据验证功能后,都手动清理回了原状(删测试脚本文件、把选题状态/`air_date` 改回去)。**以后验证功能产生的任何测试数据,验证完必须清理,不能留在这两个目录里**,不然会跟用户的真实选题池/脚本混在一起。

---

## 现在环境的实际状态

- 本地工作台服务**正在后台跑着**:`http://127.0.0.1:8765`(默认频道 `space`,`--no-open` 启动的,没有自动弹浏览器)。如果这个终端/会话已经关掉,这个进程大概率也没了,下个会话如果要用工作台,先检查 `netstat -ano | grep 8765` 有没有东西在监听,没有就重新跑:
  ```bash
  cd "D:/Claude-xiangmu/Broadcasting station"
  ./.venv/Scripts/rf.exe dashboard space --port 8765 --no-open
  ```
- `data/scripts/` 目前是空的
- `data/topics/space.json` 有 4 条选题(id `space-eat-001~004`),都是 `pool` 状态,`air_date` 都是 `null`
- `data/topics/nature.json` 不存在(nature 选题池是空的)
- [README.md](README.md) 里 `rf dashboard` 那行命令说明已经更新过,反映了新的可操作能力
