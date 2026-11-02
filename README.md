# DanmakuRepo

**无人值守的直播归档系统。** 自动发现开播 → 录制 → 把弹幕烧进视频 → 上传网盘 →
定时清理源文件。7×24 跑着，不需要人盯。

- 实盘规模：**33 个主播**同时监控（抖音为主），已连续运行数月
- 一场直播全程无人工：开播自动录、下播自动渲染、自动上传、24 小时后自动删源
- 崩溃能自愈：开机自启、跨会话迁移、优雅停止、启动对账、孤儿分段接管
- 有 **506 个模块级测试**兜底

> **第一次用？就三步：**
> 1. 双击 **`Setup.bat`** —— 装环境（Python 虚拟环境、依赖、ffmpeg、rclone）
> 2. 双击 **`Start_DMR.bat`** —— 开始录制
> 3. 出任何问题双击 **`Doctor.bat`** —— 一键体检，直接告诉你哪里坏了、怎么修
>
> 三个脚本都在项目根目录，**放哪个盘都能跑**，不依赖特定路径。

> **如果你是要接手这个项目的人或 AI**：这份 README 本身就是完整的交接文档，
> 读完就能动手。跑起来之后的坑、出事了怎么救、为什么代码长成这样，都在下面。
> 不需要看别的仓库、也不需要问原作者。

---

## 目录

1. [名称与三个必知约定](#一名称与三个必知约定)
2. [它做什么](#二它做什么)
3. [架构与目录](#三架构与目录)
4. [从零跑起来](#四从零跑起来)
5. [日常操作](#五日常操作)
6. [必须知道的十个坑](#六必须知道的十个坑)
7. [出事了怎么办](#七出事了怎么办)
8. [运维工具](#八运维工具)
9. [测试与改动纪律](#九测试与改动纪律)
10. [已知未修问题](#十已知未修问题)
11. [历史：为什么是现在这样](#十一历史为什么是现在这样)

---

## 一、名称与三个必知约定

**DanmakuRepo** = Danmaku Media Repo（弹幕媒体归档库），缩写 **DMR**。

因为缩写恰好是 DMR，所以下面这些标识符**全部沿用 DMR，不是历史遗留错误**：

| 标识符 | 实际值 | 说明 |
|---|---|---|
| 代码包名 | `DMR/` | `from DMR.Config import Config` |
| 配置键 | `dmr_engine_args` | `global.yml` 顶层键 |
| 日志文件 | `logs/DMR-YYYYMMDD.log` | 每天一个 |
| 任务配置 | `configs/DMR-<主播名>.yml` | **`DMR-` 前缀是识别标记**，去掉就不被当成任务 |
| 桌面/根目录脚本 | `DMR-*.bat`、`Start_DMR.bat` | |
| 计划任务 | `DMR_Boot` / `DMR_SessionWatch` / `DMR_Desktop` | |

**项目目录在 `F:\DanmakuRepo`**（2026-11-02 从 `F:\DanmakuRender_AutoUp` 改名）。

**但代码不依赖这个路径** —— 所有工具用 `_PROJECT_ROOT = dirname(dirname(__file__))`
自动识别自己所在的仓库根，shell 脚本用 `%~dp0`，计划任务在安装时按实际路径生成。
**克隆到任何目录都能直接跑**，不用改任何东西。

---

## 二、它做什么

```
33 个主播轮询（默认 60 秒一次）
   ↓ 检测到开播
ffmpeg 拉流录制 → ts 分段（默认每小时一段）
   ↓ 下播
渲染弹幕版 → 把 .ass 字幕烧进 mp4
   ↓
上传网盘（rclone → CloudDrive2 挂载的百度网盘）
   ↓ 默认 24 小时后
删除源视频 + 源弹幕；弹幕版永久保留
```

| 能力 | 实现要点 |
|---|---|
| **多平台录制** | 抖音（主力）、B站、虎牙、斗鱼；引擎支持 ffmpeg / streamlink / streamgears |
| **弹幕采集** | WebSocket 长连接，落 `.ass` 字幕；支持过滤（类型/关键词/用户/长度） |
| **弹幕渲染** | 逐条烧进视频，可配字体/字号/透明度/描边/停留时长；**含字形安全清洗**（见坑 9） |
| **上传** | rclone，失败 5 次重试 + 冷却；可配规则**跳过**横屏/高码率视频 |
| **延迟清理** | 上传完成后延迟删源（默认 24h），弹幕版永不删；待删清单持久化，重启不丢 |
| **状态持久化** | SQLite 记录每个分段的录/渲/传/清状态，重启后自动续跑，不重复投稿 |
| **无人值守** | 三层自启、跨会话迁移、优雅停止、启动对账（补渲染/补上传/补清理/接管孤儿） |
| **可观测** | 30 分钟心跳、状态面板、上传前时长校验、失败任务队列 |

**配置哲学**：所有任务配置只写 `url` + `output_dir`，其余全部继承
`configs/global.yml`。这是 33 个任务能压到 22 行的原因 ——
**任务文件里没写的键，都会从全局继承**。改全局等于改所有任务。

---

## 三、架构与目录

```
Setup.bat                首次安装 / 环境修复（幂等，随时可重跑）
Start_DMR.bat            启动（守护循环，崩溃自动重拉）
Doctor.bat               一键体检
_env.bat                 所有 bat 共用：解析 Python 解释器 + 补全 PATH
tools/                   30+ 运维工具，默认预览、加 --apply 才动手
unit_tests/              506 个模块级测试
configs/                 DMR-*.yml 任务配置；temp/ 是停用归档区
logs/                    DMR-*.log 日志 + dmr_state.db 状态库
直播回放/<主播>/          源视频；<主播>（弹幕版）/ 是成品

DMR/
  ├── paths.py           **所有路径的唯一来源**（根目录 / tools / logs / 快照…）
  ├── maintenance.py     周期性维护：日志轮转 / 磁盘水位 / 每日体检 / 索引页
  ├── crashdump.py       崩溃现场快照（主线程、子线程、C 层崩溃）
  ├── notify.py          开播通知（Server酱³）
  ├── __init__.py        DanmakuRepo 主类：装配组件、启动对账（reconciler）
  ├── engine.py          插件式引擎：downloader / render / uploader / cleaner 各自线程
  ├── Config/            配置合并（default.yml ← global.yml ← 任务 yml）
  ├── Downloader/        录制；Danmaku/ 写 .ass，glyphs.py 做字形清洗
  ├── LiveAPI/           各平台取流地址与弹幕连接
  ├── Render/            dmrender.py：ffmpeg 烧字幕，硬件编码失败降级软件
  ├── Uploader/          rclone 上传
  ├── Cleaner/           延迟清理 + 待删清单（logs/pending_clean.json）
  ├── state/             SQLite 状态库 + 启动对账
  ├── utils/toolsmgr.py  外部工具定位（ffmpeg / rclone / biliup，不锁版本）
  └── Task/liveevents.py 事件中枢：开播/下播/渲染/上传/清理判定（改动最多）
```

**三个最重要的路径**：

| 路径 | 是什么 |
|---|---|
| `configs/global.yml` | 全局配置（**不在 git 里**，含个人化参数）。改动**必须重启**才生效 |
| `logs/dmr_state.db` | 状态库。哪些分段录完/渲完/传完/清完。重启不丢，也是续跑依据 |
| `直播回放/<主播>/` | 源视频（24h 后自动删）；`（弹幕版）` 子目录永久保留 |

**关于路径的硬规则**：新代码不许写死盘符，也不许用 `./xxx` 这种依赖当前工作
目录的写法。一律 `from DMR.paths import p, ROOT`。
`paths.py` 里还有一个 `enter_root()`，入口脚本早期调一次就够。

---

## 四、从零跑起来

### 一句话版本

下载代码 → 双击 **`Setup.bat`** → 双击 **`Start_DMR.bat`**。

`Setup.bat` 依次处理：找 Python → 建 `.venv` → 装依赖 → 找/下载
ffmpeg、rclone → 生成 `configs/global.yml` →（可选）建桌面快捷方式和开机任务。
每一步都幂等，**环境坏了随时再跑一遍**就是修复。

### 依赖：不锁版本

| 依赖 | 要求 | 缺了会怎样 |
|---|---|---|
| Python | **3.9 以上都能跑**（推荐 3.11+，开发机 3.11.9） | 没有就无法启动 |
| ffmpeg / ffprobe | 任意较新版本 | **硬依赖**，缺了录不了 |
| rclone | 任意较新版本 | 只影响网盘上传 |
| biliup | 可选 | 只有 B 站上传才需要 |
| CloudDrive2 | 可选 | 把网盘挂成盘符给 rclone 用 |

**为什么不写死版本号**：上游哪天停止维护某个版本，用户装新的照样能跑。
代码只验证「这个 exe 能不能执行」，**不解析版本号**。

**工具放哪都能被找到**，查找顺序：

1. 环境变量 `DMR_FFMPEG` / `DMR_RCLONE` / `DMR_BILIUP`（写完整路径）
2. 项目 `tools\` 目录
3. 系统 PATH
4. **注册表里的最新 PATH** —— 进程环境的 PATH 是启动那一刻的快照，
   用户刚装完工具时它还是旧的，只查进程 PATH 会误报"没装"
5. `C:\Program Files\...`、`C:\User Program Files\...` 下名字带工具名的目录

手动装也行：`winget install ffmpeg` / `winget install rclone`，
或者把 exe 直接丢进 `tools\`。

### 路径：放哪个盘都行

项目里**没有任何写死的盘符**。所有路径都从 `DMR/paths.py` 的 `ROOT` 派生
（= 该文件所在包的上一级），所以克隆到 `D:\工具\DMR` 也能直接跑。
启动脚本全部用 `%~dp0`，不再有 `F:` 开头的切盘命令。

要换数据位置就设环境变量：

| 变量 | 作用 | 默认 |
|---|---|---|
| `DMR_DATA_ROOT` | 录制数据根目录 | 项目根 |
| `DMR_SNAPSHOT_DIR` | 配置快照目录 | `<项目>\backups\配置快照` |
| `DMR_BACKUP_DIR` | 大件备份目录 | `<项目>\backups` |

> 旧版本的配置快照写在 `F:\_DMR配置快照`（项目外）。第一次运行新版时，
> 如果新位置为空、旧位置存在，会**自动复制**一份过来（只复制，不删原件）。

### 启动

```bat
Start_DMR.bat          :: 守护循环，进程退出后 10 秒自动重拉（有窗口）
```

所有启动脚本都通过 `_env.bat` 解析解释器，顺序是
`.venv` → 项目内 `python\` → `py -3` → PATH 里的 `python`。
所以**没跑过 Setup.bat 但机器上已有 Python** 时，直接双击也能起。

### 桌面快捷方式

```bat
python tools\install_desktop_links.py        :: 建 6 个常用入口
python tools\install_desktop_links.py --all  :: 再加"推送全部"
```

生成的是**真正的 .lnk**，指向项目里的 bat。项目挪了位置只要重跑一次。
桌面上那些旧的 .bat 副本会被移到 `backups\desktop-shortcuts-<日期>\`（不是删除）。
**用户自己的 yml 模板（`DMR-某某.yml`）永远不动。**

### 三层自启（生产机已配好，换机器要重建）

| 层 | 名字 | 触发 | 作用 |
|---|---|---|---|
| 1 | Startup `DMR_AutoUp.cmd` | 用户登录 | 交互式启动，**有可见窗口** |
| 2 | 计划任务 `DMR_SessionWatch` | 登录 + 解锁 | 把 DMR 迁到当前会话，窗口跟着人走 |
| 3 | 计划任务 `DMR_Boot` | 开机 | session 0 常驻守护，无人登录时兜底 |

重建第 3 层：`python tools\install_boot_task.py`（需管理员，会自己提权）。
它**运行时生成任务**，不再依赖 `tools/boot_task.xml` 那个写死路径的模板。
第 2 层：`tools/install_session_tasks.ps1`。第 1 层：往 Startup 目录放一份等价 cmd。

> 计划任务拉起的进程**窗口必然隐藏**（Windows 行为，不是 bug）。
> 要窗口只能由用户交互启动 —— 双击 `DMR-启动`。

### 换机器 / 灾难恢复

能直接跑起来的东西在私有仓库 `DanmakuRepo-Full`：除了代码还有 `configs/`
（含全部主播链接）和 `logs/dmr_state.db`。**克隆到任意目录都行**：

```bat
git clone https://github.com/SylvanLee205/DanmakuRepo-Full
cd DanmakuRepo-Full
Setup.bat
Start_DMR.bat
```

**只有 ffmpeg 是真正的硬前提**，其余缺了都能跑（功能打折）：

| 缺什么 | 后果 |
|---|---|
| Python（3.9+） | 完全起不来。`Setup.bat` 会提示下载地址并打开浏览器 |
| **ffmpeg / ffprobe** | 录不了。`Setup.bat` 可自动下载到 `tools\` |
| rclone | 录制渲染照常，只是不传网盘 |
| CloudDrive2 | 上传通道不通（rclone 的目标盘不存在） |

计划任务要自己重建（见上一节）。纯手动跑则不建也能用。

⚠️ 私有仓库含主播直播间链接，**绝不能改成 public**。

---

## 五、日常操作

| 想干什么 | 怎么做 |
|---|---|
| **加主播** | 复制抖音直播间链接 → 双击 `DMR-添加主播.bat`。自动取名、写配置、**热加载不用重启** |
| **看状态** | 双击 `DMR-看实时日志.bat`，或 `python tools/dmr-status.ps1` |
| **回看录播** | 打开项目里的 `index.html`（每天 06:00 自动重建）。想立刻生成：`python tools\build_index.py --open` |
| **磁盘快满了** | 不用管——低于 60GB 会自动删已渲染完的源视频；低于 20GB 会暂停开新任务并发通知 |
| **停用主播** | **两步**：① 配置挪进 `configs/temp/` ② `python tools/purge_task_state.py --apply` |
| **重新启用** | 配置从 `configs/temp/` 挪回 `configs/`（热加载）。历史状态没了，进度从头记 |
| **改全局配置** | 改 `configs/global.yml` → **重启 DMR** |
| **重启** | `python tools/stop_dmr.py`（优雅停止）→ `Start_DMR.bat` |
| **改完代码** | 跑测试 → **重启 DMR**（代码不热加载） |

**桌面脚本**（生产机 `C:\Users\Administrator\Desktop\`）：

```
DMR-启动.bat          拉起 DMR（已在跑会安全跳过，不会双开）
DMR-停止.bat          优雅停止（含录制子进程）
DMR-看实时日志.bat     滚动日志 + 定期状态行
DMR-添加主播.bat      剪贴板里的链接 → 新任务
DMR-重启后检查.bat     重启后自检：自动登录、会话位置、窗口可见性
DMR-推送全部.bat      推两个仓库（公开脱敏 + 私有完全体）
```

> 平时只有「添加主播」和「看实时日志」会用。启动/停止是应急操作 ——
> 正常流程里开机自动起，不用碰。

---

## 六、必须知道的十个坑

按"会不会咬人"排序。**前五个都实际造成过事故。**

**1. 改 `DMR/` 下的代码必须重启才生效。**
热加载只覆盖 `configs/`，不覆盖代码。踩过三次 —— 改完不重启，以为修好了，
其实跑的还是旧代码。

**2. 改 `configs/global.yml` 同样必须重启。**
DMR 检测到变化只会打一行警告"需要重启程序才会生效"，**不会自动应用**。

**3. 停用主播必须两步。**
只把配置挪进 `configs/temp/` 会让一致性校验拒绝启动，守护循环每 10 秒重拉
→ **崩溃循环刷日志**（2026-10-23 实际刷了 26 个日志文件）。
第 2 步 `tools/purge_task_state.py --apply` 清状态库里这个任务的记录
（先自动备份 `.db`，**不碰磁盘录像**）。

**4. 任务名 ≠ 录像目录名。**
`DMR-<任务名>.yml` 的文件名和它的 `output_dir` 没有必然关系，出现过三次
（`DMR-迪佳奥特曼.yml` → `直播回放/我已经不会再流泪`）。
找录像先看配置里的 `output_dir`，别按任务名找。

**5. 重启前确认没有正在渲染的任务。**
正在录的分段会停在 `[正在录制]`、rename 不执行；正在渲染的会半途而废
（2026-10-30 因此丢过一场）。`stop_dmr.py` 默认优雅停止能兜住，
但**手动 kill 没有这个保护**。

**6. `.bat` 文件必须纯 ASCII。**
cmd.exe 用系统代码页（GBK）解析 bat，`chcp 65001` 生效之前就已经读完了。
中文注释会让命令解析错乱，表现为"双击后只弹一句请按任意键"。写完立刻校验：

```bash
LC_ALL=C grep -q '[^ -~]' xxx.bat && echo "有非 ASCII" || echo "OK"
```

**7. `glob` 匹配不了 `[正在录制]`。**
方括号是 glob 的字符类语法，会一个都匹配不到。必须用 `os.listdir` + `startswith`。
踩过两次。

**8. 上传前会校验 mp4 时长，读不出就拒传。**
这是防半成品的闸门，但**它有误报**：加 `-movflags +faststart` 的 mp4 要等编码
结束后把索引重写到文件头，此刻探测会失败（2026-11-02 实际误跳过一段完好的
33 分钟视频）。看到"读不出时长"，先用 ffprobe 确认文件是不是真的坏了：

```bash
ffprobe -v error -show_entries format=duration -of csv=p=0 "xxx.mp4"
```

**9. 一条 ffmpeg 断言可能对应多个不相干的原因。**
`Assertion ... bytewidth failed at libavutil/imgutils.c:351` 背后有三个独立真凶：
**无字形字符**（注音ㄓ U+3103）、**彩色 emoji 字体**（回退到 SegoeUIEmoji）、
**源视频损坏帧导致 libass 输出帧 stride 算错**。
排查必须分层：`-f null`（不编码）隔离字幕层，换 `libx265` 隔离编码层。
详见 [`docs/排查记录-20261102-渲染崩溃三个真凶.md`](docs/排查记录-20261102-渲染崩溃三个真凶.md)。

**10. DMR 日志里的"原因判断"不可信。**
它只看退出码就写"GPU 编码会话被其他程序占用"，而实际可能是 libass 字幕帧坏。
报错要回到 ffmpeg 原始输出看。

---

## 七、出事了怎么办

| 症状 | 大概率原因 | 处理 |
|---|---|---|
| DMR 起不来，日志刷 Traceback | 状态库与配置不一致（刚停用过主播） | `python tools/purge_task_state.py --apply` |
| 守护循环每 10 秒重拉、日志暴涨 | 同上，崩溃循环 | 先 `DMR-停止.bat`，再 purge_task_state |
| 某主播渲染反复失败 | 弹幕字符 / 硬件编码器 / 源视频损坏 | 看日志里那条渲染错误后面的 ffmpeg 原始输出 |
| 磁盘被占满 | 源视频没被清（跳过上传的分段曾有 bug） | `python tools/clean_skipped_backlog.py`（默认预览） |
| `[正在录制]` 文件越积越多 | 进程被杀留下的孤儿 | `python tools/rename_orphans.py --apply`，下次启动自动接管 |
| 上传一直失败 | CD2 / 网盘 / 网络 | 看 `logs/cd2_watchdog.log`；上传有 5 次重试 + 冷却 |
| 重启后没有 DMR 窗口 | 计划任务拉起的进程窗口必隐藏 | 正常。用 `DMR-看实时日志.bat` 看状态；要窗口就双击 `DMR-启动.bat` |
| RDP 连不上（报 0x5） | 单账号单会话被占 | 关自动登录 + 注销 console 会话 |

**通用三步**：

```bat
Doctor.bat                                        :: 1. 一键体检（先跑这个）
python tools/dmr-status.ps1                       :: 2. 看整体状态
findstr /C:"[error]" logs\DMR-*.log               :: 3. 看最近的错
python tools\stop_dmr.py                          :: 4. 优雅停止
Start_DMR.bat                                     :: 5. 重启
```

`Doctor.bat` 会逐项检查 Python / 依赖 / ffmpeg / rclone / 磁盘 / 配置 /
状态库 / 进程 / 计划任务 / 通知通道，每条都给出「现状 + 怎么修」。
加 `--export` 会打包一份诊断 zip 到 `.temp\`，直接发给 AI 就能定位问题。

---

## 八、运维工具

全部在 `tools/`，**默认都是预览模式，加 `--apply` / `--force` 才真动手**。

### 自动维护（不用管，DMR 自己会做）

`DMR/maintenance.py` 每分钟 tick 一次，按各自节奏干活。全部动作失败只记
warning，**绝不影响录制**。配置在 `global.yml` 的 `maintenance:` 段。

| 什么时候 | 做什么 | 为什么需要 |
|---|---|---|
| 每 6 小时 | **日志轮转**：删超过 14 天或总量超 500MB 的旧日志（今天的保留） | 4 个日志文件曾涨到 36MB，只增不减 |
| 每 5 分钟 | **磁盘水位**：低于 120GB 记警告，低于 60GB 自动删「已渲染完」的最旧源视频，低于 20GB 再暂停开新任务 | 盘满了 ffmpeg 写失败 = 丢内容 + 状态库变脏 |
| 每天 05:00 | **定时体检**：跑 `doctor.py` 的全部检查，**只有严重问题才发通知** | 出问题时人往往几天后才发现 |
| 每天 06:00 | **重建索引页** `index.html` | 想回看时不至于翻文件夹 |
| 崩溃时 | **现场快照** `.temp/crash-*.txt`（完整 traceback + 所有线程栈 + 日志尾部 + 内存） | 子线程崩了以前完全静默 |

**磁盘清理的安全规则**（每条都对应一次真实教训）：
跳过 `[正在录制]`、跳过 `.part`/`.ass` 等中间产物、**跳过弹幕版成品本身**、
必须有对应的「（弹幕版）」产物才允许删、只删 2 小时没动过的、从最旧开始删。

> ⚠️ 2026-11-02 实测抓到过一个 bug：判断"有没有对应弹幕版"时，
> 弹幕版**自己**也满足条件 —— 差点把成品删光。现在先排除带「（弹幕版）」的文件。

### 手动工具

| 工具 | 干什么 |
|---|---|
| `bootstrap.py` | **首次安装 / 环境修复**：venv、依赖、ffmpeg、rclone、配置 |
| `doctor.py` | **一键体检**，`--export` 打诊断包 |
| `build_index.py` | 生成录播索引页 `index.html`（搜主播 / 筛日期 / 点开就播） |
| `install_desktop_links.py` | 在桌面建 .lnk 快捷方式（`--all` 含推送脚本） |
| `install_boot_task.py` | 注册/注销开机计划任务（运行时生成，不依赖 XML 模板） |
| `add_room.py` | 读剪贴板链接 → 自动取名 → 写 `configs/`，热加载 |
| `stop_dmr.py` | **优雅停止**：ffmpeg 收到 `q` 写完当前段并改名，超时才硬杀 |
| `autostart_launch.py` | 登录自启 + 跨会话迁移（窗口跟着人走） |
| `rename_orphans.py` | 把 `[正在录制]` 孤儿登记进状态库，启动对账自动接管 |
| `clean_skipped_backlog.py` | 清"命中跳过上传规则却永不清理"的积压源视频 |
| `purge_task_state.py` | 清停用任务的状态库记录（先备份 .db） |
| `backup_configs.py` | 配置快照：snapshot / verify / list / restore |
| `backup_to_disk.py` | 整个项目异盘备份（自动挑盘，可 `--with-videos`） |
| `pack_cloud_backup.py` | 打包代码 + git 历史 + bundle，传网盘做异地副本 |
| `sync_full_backup.py` | 同步 `configs/` + 状态库到私有完整副本 |
| `push_all.py` | **一条命令推两个仓库**：公开（脱敏）+ 私有（完全体），默认预览 |
| `install_session_tasks.ps1` | 幂等重建 SessionWatch / Desktop 计划任务 |
| `dmr-status.ps1` | 状态面板：进程、会话位置、窗口可见性、自动登录有效性 |
| `post_boot_check.py` | 重启后自检：自动登录四要素、DMR 起在哪个会话 |

---

## 九、测试与改动纪律

```bash
python -B -m unittest discover -s unit_tests -t .
```

**506 个测试，全绿（5 个 expected failure）。**

> 旧版本在找不到 ffmpeg 时会 `input()` 等你回车，无控制台环境下表现为卡死。
> 2026-11-02 起 `toolsmgr` 里**已无任何 `input()`**：找不到就打印指引 +
> 写 `logs/startup_error.log` 并退出，不再挂住。

**改代码前的三条**：

1. 确认你要改的键是不是**从 global.yml 继承**的 —— 任务配置里没写的都会继承。
   改全局等于改 33 个任务。
2. 看 [`docs/TODO.md`](docs/TODO.md) 的未完成项，别重复劳动。
3. 改完**跑测试**，然后**重启验证** —— 只跑测试不算完，热加载不覆盖代码。

**改完记得同步两条线**：本地 `master`（完整历史）→ 公开分支（脱敏）→ 私有仓库（完全体）。
一条命令搞定：

```bash
python tools/push_all.py            # 预览：只报告会推什么，不动任何东西
python tools/push_all.py --apply    # 同步 + 提交 + 推送两个仓库
```

| 仓库 | 内容 | 说明 |
|---|---|---|
| 公开 `DanmakuRepo` → `main` | `master` 的树 + 10 个发布脚手架（示例配置、脱敏工具） | **脱敏**：无 configs/、无状态库、无内网地址 |
| 私有 `DanmakuRepo-Full` → `main` | `master` 全部内容 **+ `configs/` + `.temp/` + 状态库** | **完全体**，克隆下来放到 `F:\DanmakuRepo` 就能直接跑 |

工具会拒绝在 `master` 有未提交改动时推送（宁可让你先整理，也不推半截内容）。
两个 worktree（`-prodsync` / `-full`）由 `git worktree` 维护 ——
**不要在生产目录里切分支**，DMR 正跑着。

---

## 十、已知未修问题

| 问题 | 影响 | 建议 |
|---|---|---|
| **hevc_qsv 硬件编码不稳定** | 长视频（>20 分钟）渲染有概率崩，靠"失败降级 libx265"兜住，但每次白等两轮重试 | **更新 Intel Arc 显卡驱动**（疑与 2026-10-20 蓝屏 0x113 同源） |
| 源视频损坏帧无检测 | 录制丢包只有渲染时才以 stride 错误爆出来 | 录制完成时统计 concealed errors，超阈值告警 |
| 渲染前无内容占比预检 | 源视频只录到 31% 时仍会渲染 3 分钟，最后被时长校验拒掉，白烧显卡 | 渲染前用 ffprobe 快速算有效内容占比 |

完整清单与已确认缺陷见 [`docs/TODO.md`](docs/TODO.md)。

---

## 十一、历史：为什么是现在这样

**它不是从零写的，也不是原样照搬别人的。** 演进路径：

```
SmallPeaches/DanmakuRender v5（架构来源：引擎/消息/插件/配置合并/下载器抽象）
        ↓ 2026-10 合并一次，之后上游停更（最后提交 2026-10-10）
本项目的深度定制
        ├─ 上传层重建：B站（biliup） → rclone + 网盘
        ├─ 新增：SQLite 状态库、启动对账、延迟清理
        ├─ 新增：三层自启、优雅停止、孤儿接管、30+ 运维工具
        ├─ 新增：506 个模块级测试
        └─ 改名：DanmakuRender-AutoUp → DanmakuRepo
```

**上游架构完整保留**（引擎、消息、插件、配置合并、下载器抽象一行没改），
换掉的全是外围 —— 那套架构本身是好的，重写它风险高收益低。
保留包名 `DMR/` 也是同一个判断：改它要动 363 处 import 和运行中的进程路径，
而 DMR 这个缩写本来就成立。

**踩过的坑都留在代码和文档里**，README 之外的部分按需查：

| 想看什么 | 去哪 |
|---|---|
| 每个版本改了什么、升级注意 | [`docs/CHANGELOG.md`](docs/CHANGELOG.md) |
| 未完成事项、已确认缺陷 | [`docs/TODO.md`](docs/TODO.md) |
| 架构事实、产物语义、关键决策 | [`docs/project_state.md`](docs/project_state.md) |
| 已完成工作的技术明细（根因/实现/教训） | [`docs/maintainer-log.md`](docs/maintainer-log.md) |
| 生产事故的完整排查复盘 | [`docs/排查记录-20261102-渲染崩溃三个真凶.md`](docs/排查记录-20261102-渲染崩溃三个真凶.md) |
| 历史快照、一次性报告、网盘运维专题 | [`docs/archive/`](docs/archive/)（22 篇，目录里 `README.md` 是清单） |

---

## 致谢

上游与依赖：[SmallPeaches/DanmakuRender](https://github.com/SmallPeaches/DanmakuRender)
（架构来源）、THMonster/danmaku、wbt5/real-url、ForgQi/stream-gears、
ffmpeg / libass / rclone / fontTools / psutil。

**本程序仅供研究学习使用。**
