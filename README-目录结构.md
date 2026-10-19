# DanmakuRender_AutoUp —— 目录结构与维护说明

> 这份文件是为了防止以后再搞混目录。**改动任何东西之前先看这里。**

---

## 一、F 盘的目录布局（2026-10-05 整理后）

| 目录 | 作用 | 能不能删 |
|---|---|---|
| **`F:\DanmakuRender_AutoUp`** | ★ **生产环境，正在跑的就是它** | ❌ 绝对不能删 |
| `F:\DanmakuRender_Mod` | 魔改版开发副本（git 仓库，推 GitHub 用） | ❌ 建议保留 |
| `F:\_历史任务配置备份_20261005` | 从已删除的 AutoClean 里抢救出的 104 个任务配置 | 可删 |
| `F:\_启动脚本备份_20261005-031303` | 整理前的 bat / 快捷方式备份 | 可删 |

**已经删除的旧副本**（2026-10-05 清理，以后不该再出现）：
- ~~`F:\123Pan_DanmakuRender`~~ → 已改名为 `DanmakuRender_AutoUp`
- ~~`F:\DanmakuRender-2026.01.10`~~ → 已删除（空壳旧备份）
- ~~`F:\DanmakuRender_AutoClean`~~ → 已删除（configs 已备份出来）
- ~~`F:\DanmakuRender-魔改版`~~ → 已改名为 `DanmakuRender_Mod`

### 历史教训

之前 F 盘有 **4 份** DMR，而且两个 `Start_Render.bat` 的 `cd` 路径**互相对调**了：

```
F:\123Pan_DanmakuRender\Start_Render.bat   里写的是  cd "F:\DanmakuRender-2026.01.10"
F:\DanmakuRender-2026.01.10\Start_Render.bat 里写的是  cd "F:\123Pan_DanmakuRender"
```

结果双击任何一个、或者开机自启，跑的都是 `2026.01.10` 里那份 **6 月的旧代码**，
所有修复（三道防线、跳过上传、GOP、rclone 上传）**一个都没生效**，而且没人发现。

**所以：每个 bat 的 `cd` 必须指向它自己所在的目录。** 改完务必用
`Start-Render 后看日志写在哪个目录` 来验证。

---

## 二、启动入口（2026-10-19 晚 重新梳理）

> ⚠️ **2026-10-19 14:42 真实事故**：系统蓝屏（0x113 显卡驱动）重启后，
> 自动登录占住了 console 会话，而 `fSingleSessionPerUser=1`，
> 于是同一个账号的 RDP 被拒（0x5「已建立另一个连接」）——人在几十公里外，差点进不来。
> 之后为了能 RDP，`AutoAdminLogon` 被关成 0。**代价是：重启后没人登录，启动文件夹的入口不会执行。**

| 位置 | 作用 | 状态 |
|---|---|---|
| **`Install_Boot_Task.bat`** | 建「开机启动」计划任务（Administrator + 密码），**不占 console、不需要登录** | ★ 最强保险，需双击一次并输入密码 |
| `Remove_Boot_Task.bat` | 删除上面那个计划任务 | 回滚用 |
| **`Fix_RDP_Lockout.bat`** | 万一 RDP 又被拒：关掉自动登录并打印 `logoff 1` 指令 | 桌面有同名入口 |
| Startup\`DanmakuRender_AutoUp.cmd` | 登录后自启（调 `tools\autostart_launch.py`，带 3 次重试） | 兜底；已装计划任务时会被守卫跳过 |
| `Start_Render.bat` | 原地守护循环（程序退出 10 秒后重拉，纯 ASCII + CRLF） | 正常 |
| `Run_DMR.bat` | 计划任务的动作：先跑守卫，没实例才 `call Start_Render.bat` | 正常 |
| 桌面 `DMR-启动.bat` / `DMR-停止.bat` | 手动启停（停止会连子进程一起清） | 正常 |
| 桌面 `DMR-重启后检查.bat` | 一键自检（进程/版本/任务数/ERROR/状态库/开机任务） | 正常 |

### 2026-10-19 15:35 的访问配置（事故后最终值）

```
HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server
    fSingleSessionPerUser = 1     ← 恢复原值：RDP 接管 console，行为与以前一致
HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon
    AutoAdminLogon  = 1           ← 恢复开机自动登录（密码在 LSA，不用重输）
    ForceAutoLogon  = 0           ← 注销后不强制秒登
```

> **2026-10-19 14:44 那次 0x5 的真正原因（推断已收敛）**：`已与远程电脑建立了另一个连接`
> 是 **`/admin` 连 console 会话时**的典型报错。开机 14:43:48、自动登录完成 14:44:44，
> 如果在那之间去连，console 还在"正在登录"，接管被拒。
> **等 1~2 分钟（或等 DMR 启动通知）再连**，就不会再撞上。
>
> 这也解释了"以前点开就在桌面、能看到 DMR 窗口"——你连的是**已经登录好的那个会话**。
> 自动登录被关掉的那两小时里，RDP 只能新建会话，所以才会"像重新开机、看不到 DMR"。

> ⚠️ 如果把 `fSingleSessionPerUser` 改成 0，普通 RDP 会**新建独立会话**（看不到 console 里的 DMR 窗口），
> 只有 `/admin` 才连 console。想保持"随便怎么连都落到同一个桌面"，就保持 1。



> 旧的三个 `.lnk`（`Start_Render.bat - 快捷方式` 等）指向已删除的 `F:\DanmakuRender-2026.01.10`，已移入 `backups\desktop-shortcuts-20261019`。

### 为什么登录自启曾经静默失效

原实现是 `explorer.exe "Start_Render.bat"`。**登录瞬间 explorer 还没初始化完**，这个调用会被丢弃，
`autostart.log` 里只有「准备启动」却永远没有进程（10-19 14:44/14:52/14:54 三次都这样）。
现在改为 `tools\autostart_launch.py`：CreateProcess detached 启动 + 25 秒后复查 + 最多重试 3 次，每次结果都写日志。

### 关于 `timeout` 的坑

`Start_Render.bat` 原来的重启延时用 `timeout /t 10`。**没有控制台时（计划任务 / session 0）它会立刻失败**，
循环就变成零延时疯狂重启。已改成 `ping -n 11 127.0.0.1`。

> ℹ️ 看到**两个** python 进程（`.venv\Scripts\python.exe` 与 `C:\Python311\python.exe`）是正常的：
> 前者是 Windows venv 启动器，后者才是真正在跑的 DMR。**不要**杀其中一个"重复进程"。
> **⚠️ 不要用 PowerShell 的 `Start-Process` 启动 `Start_Render.bat`** —— 它会成为调用者的子进程，
> 调用者一退出录制就被带走。要么双击 bat，要么用计划任务。



---

## 二·五、日常启停（2026-10-19 新增，双击即可）

| 想做什么 | 双击哪里 | 背后发生了什么 |
|---|---|---|
| **启动** | 桌面 `DMR-启动.bat`（或项目根 `Start_DMR.bat`） | 先查有没有实例 → 没有才拉起 `Start_Render.bat`（守护 + 录制） |
| **停止** | 桌面 `DMR-停止.bat`（或项目根 `Stop_DMR.bat`） | 停守护 → 停 DMR → 停 streamgears/ffmpeg 子进程；**不会重启** |

两者都是纯 ASCII + CRLF 的批处理，内部只调用 `tools\autostart_guard.py` 与 `tools\stop_dmr.py`。

### 为什么不能直接关窗口 / 按 Ctrl+C

- **关窗口**：`cmd` 和 python 一起没了，但 `streamgears`/`ffmpeg` 这类孙进程可能残留，
  于是同一个主播两路录制 → 孤儿 `[正在录制]` 分段（2026-10-07 踩过）。
- **Ctrl+C**：python 退出后，`Start_Render.bat` 会在 **10 秒后自动把它拉起来**，
  等于"没停"。

所以"停"必须**先停守护**，再停主进程和子进程 —— 这正是 `Stop_DMR.bat` 做的。
如果是"停完马上要重启"，直接用 `tools\cleanup_duplicate_streamgears.py`（会多等 150 秒让孤儿分段沉淀）。

> `.cmd` 与 `.bat` 的关系：两者都是 `cmd.exe` 解释的批处理，语法完全相同；
> `.cmd` 只是 NT 时代为区分 DOS 的 `.bat` 而加的扩展名。启动文件夹里放 `.cmd`
> 是因为它可以被直接执行（而失效的 `.lnk` 无法在本机重建：没有 pywin32，COM 也被安全策略禁用）。



---

## 三、中断录制恢复（`.part` 文件）

录制被强制中断（关窗口 / 崩溃 / 断电）时，biliup 已经写下的内容会留在：

```
直播回放/<主播>/[正在录制]<主播>-<YYYYMMDDHHMMSS>-<uuid>.flv.part
```

程序本身**不会处理**这个文件。

### ★ 现在是自动的（2026-10-05 起）

**程序每次启动时会自动检测并恢复**，不需要你做什么。看日志第 3 行左右会有一句：

```
[recover_part][info]: [恢复] 没有发现中断的 .part 文件。
```
或者
```
[recover_part][info]: [恢复] --- 掉了颗兔牙\[正在录制]....flv.part
[recover_part][info]: [恢复]     恢复完成: part → mkv 转封装；弹幕已配对
```

**为什么放在 `main.py` 而不是 bat 里**：这样无论你怎么启动（双击 `main.py`、
双击 `Start_Render.bat`、计划任务、开机自启）**都会执行**，不依赖某个特定脚本。

启动参数（一般用不到）：

| 参数 | 作用 |
|---|---|
| `--no_recover` | 本次启动**关闭**自动恢复 |
| `--recover_wait` | 改成**同步**执行（等恢复渲染完再开始录制）；默认后台跑 |
| `--recover_min_age N` | 只恢复最后修改早于 N 分钟的 `.part`，默认 **2** |

**安全性**：只处理最后修改早于 **2 分钟**的文件（程序刚启动时正在录的分段一定很新）；

> ⚠️ **为什么是 2 分钟而不是 10**：程序启动时会先把上一次残留的 `.part` 扫一遍，
> 此时 DMR 自己的下载任务才刚开始拉起，不会有"正在录制中"的分段。
> 阈值设 10 分钟会漏掉上次崩溃/重启留下的新 `.part`（通常只有几分钟），
> 要等**下一次**启动才能捡回来。2 分钟既覆盖这种情况，又留足余量
> （单个分段通常 1 小时，不可能 2 分钟就写完）。
`ffprobe` 读不出来的跳过；恢复完的文件不再是 `.part` 所以天然幂等；
整个过程包在 `try/except` 里，**任何异常都不会影响主程序启动**。

### 手动跑（想提前处理、或想先预览）

```powershell
cd F:\DanmakuRender_AutoUp

# 1. 先扫描预览（不改任何文件）
.\.venv\Scripts\python.exe tools\recover_part.py

# 2. 确认没问题后，恢复 + 渲染 + 上传
.\.venv\Scripts\python.exe tools\recover_part.py --apply

# 其他用法
#   --no-render       只恢复不渲染
#   --no-upload       渲染但不上传
#   --min-age 60      只处理 60 分钟没动过的（更保守）
#   --upload-only <文件或目录>   只上传，跳过恢复渲染
```

它做的事：扫描 `.part` → `ffprobe` 验证可读 → 按任务配置的命名规则改名成
`<主播>-YYYY年MM月DD日HH点MM分.mkv`（和正常录制完成的分段完全一样）
→ 配套的 `[正在录制]...PartNNN.ass` 弹幕一起改名 → 渲染弹幕版 → rclone 上传。

> 实际战绩：2026-10-05 用它救回了 `掉了颗兔牙-2026年10月05日02点33分`
> （145.8MB 的 `.part`，12.4 分钟内容），渲染成 55.7MB 的弹幕版并上传到百度网盘。

---

## 四、清理与上传逻辑（当前生效的配置）

```
弹幕版渲染完成 ─┬─ 原视频 .mkv  → 立即删除（不等上传）
                ├─ 弹幕版 .mp4  → 立即 rclone 上传百度网盘
                └─ 弹幕版 .mp4  → 本地保留做备份

上传目标: cd2:百度网盘/DMR录播/{TASKNAME}   （cd2 = 百度网盘 WebDAV）
跳过上传: 横屏 且 (码率>=2500kbps 或 帧率>=40fps) → 不传
```

**⚠️ 改 `DMR/Task/liveevents.py` 的清理逻辑前，先读 `DanmakuRender_Mod\README-魔改版.md`
里的 🔴 事故说明**（2026-10-05 曾因"渲染期间删掉输入文件"丢过一段录播），
并务必跑回归测试：

```powershell
.\.venv\Scripts\python.exe tools\test_clean_order.py
```

---

## 五、其他有用的自检脚本（`tools\`）

| 脚本 | 用途 |
|---|---|
| `test_clean_order.py` | ★ 清理时机回归测试（渲染期间不能删输入） |
| `test_skip_upload.py` | 跳过上传规则的单测（30 个用例） |
| `test_skip_upload_flow.py` | 清理与上传解耦的集成测试 |
| `test_baidu_upload.py` | 百度网盘上传链路端到端测试 |
| `check_recordings.py` | 检查已录制文件的完整性（解码/时长/码率） |
| `compare_engines.py` | 从日志统计各录制引擎的失败率 |
| `ab_test_engines.py` | 真实引擎对测（需要主播在播） |
| `fix_failed_renders_args.py` | 修复失败任务里保存的坏渲染参数 |
| `recover_part.py` | ★ 中断录制恢复 |
