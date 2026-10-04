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

## 二、所有启动入口（都已指向 AutoUp）

| 位置 | 目标 |
|---|---|
| 桌面 `Start_Render.bat - 快捷方式.lnk` | `F:\DanmakuRender_AutoUp\Start_Render.bat` |
| 桌面 `DanmakuRender_AutoUp - 快捷方式.lnk` | `F:\DanmakuRender_AutoUp` |
| 桌面 `configs - 快捷方式.lnk` | `F:\DanmakuRender_AutoUp\configs` |
| **开机自启** `Startup\Start_Render.bat - 快捷方式.lnk` | `F:\DanmakuRender_AutoUp\Start_Render.bat` |
| 开始菜单 `configs.lnk` | `F:\DanmakuRender_AutoUp\configs` |

`Start_Render.bat` 的行为：发一条推送通知 → `cd` 到项目目录 → 跑 `main.py`
→ 程序退出后等 10 秒 → `goto loop` 重新拉起（守护进程）。

**⚠️ 不要用 PowerShell 的 `Start-Process` 启动它。** 那样它会成为调用者的子进程，
调用者（比如某个终端会话或 AI 助手界面）一退出，录制程序会被一起带走。
**要启动就双击 bat 或快捷方式**（父进程是 explorer.exe，独立安全）。

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
| `--recover_min_age N` | 只恢复最后修改早于 N 分钟的 `.part`，默认 10 |

**安全性**：只处理最后修改早于 10 分钟的文件（程序刚启动时正在录的分段一定很新）；
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
