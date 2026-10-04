# DanmakuRender-魔改版

基于 [SmallPeaches/DanmakuRender](https://github.com/SmallPeaches/DanmakuRender) **v5** 的个人魔改版。
原版完整保留在 `F:\123Pan_DanmakuRender`，未做任何改动；本目录是在其基础上复制并修改的独立版本。

- 原版项目：https://github.com/SmallPeaches/DanmakuRender/tree/v5
- 本魔改版主要面向：**抖音直播录制 → 渲染弹幕版 → 同时上传 B站 + 123网盘 → 清理原视频** 这条流水线

---

## 一、运行方式

和原版完全一致，没有引入新的依赖：

```
python main.py                     # 正常启动
python main.py --skip_update       # 跳过版本检查
python Start_Render.bat            # Windows 一键启动
```

`configs/global.yml` 已经是配置好的可用状态（B站 + 123网盘、GOP 关闭、清理规则已配）。

> ⚠️ `.venv` 没有复制过来。如果你想让新版本独立运行，把原版的 `.venv` 拷过来即可：
> `xcopy /E /I F:\123Pan_DanmakuRender\.venv F:\DanmakuRender-魔改版\.venv`

---

## 二、相对原版的改动清单

### 1. 【新增】两个视频编码问题自动检查

**背景**：原版配置里 `-global_quality 32` 少了 `:v` 流说明符，ffmpeg 会把这个质量参数
**同时套到音频编码器上**。音频用的 `libopus` 只支持码率模式，于是渲染必然失败：

```
[libopus @ ...] Quality-based encoding not supported, please specify a bitrate and VBR setting.
[enc:libopus @ ...] Error while opening encoder - maybe incorrect parameters
```

输出文件 0 字节，而清理规则会把源视频删掉 —— 录播直接永久丢失。

**改动**（`DMR/Render/dmrender.py`）：
- 渲染器初始化时检查 `vencoder_args` / `aencoder_args`，发现 `-global_quality`、`-crf`、`-cq`、
  `-qp`、`-qscale`、`-qmin`、`-qmax` 这类参数没带 `:v` 时，直接打 WARNING 并给出改法。
- 现在 `configs/global.yml` 里写的是 `-global_quality:v`，不会再踩这个坑。

### 2. 【新增】GOP 按帧率自动计算（`gop_multiplier`）

`configs/global.yml` → `render_args.dmrender`：

```yaml
# GOP（关键帧间隔） = 源视频帧率 x gop_multiplier
gop_multiplier: ~      # 8 = 每8秒一个关键帧；~ = 关闭，用编码器默认值
gop_default_fps: 30    # 探测不到帧率时的兜底值
```

- `gop_multiplier: 8` → 1080P60 得到 `-g 480`，1080P30 得到 `-g 240`
- 帧率用 `ffprobe` 的 `r_frame_rate` 实时探测（`DMR/utils/ffprobe.py` 新增 `get_fps()`）
- 如果你自己在 `vencoder_args` 里写了 `-g`，自动计算会自动跳过，以你的为准
- 渲染日志会打印：`GOP: 源帧率 22 x 8 = 176 帧关键帧间隔。`

**实测验证**（源视频 22fps，gop_multiplier=8）：

```
关键帧位置: [0, 176, 352, 528]
关键帧间隔: [176, 176, 176]     ← 完全符合预期
```

### 3. 【替换】YouTube 上传 → rclone 网盘上传

原版的 `youtubev3` 上传引擎依赖 `googleapiclient` / `oauth2client`，而 `requirements.txt`
里根本没有这些包，一旦启用必然 ImportError。本魔改版**直接删除**了它，改为 rclone。

被删掉的东西：
- `DMR/Uploader/youtubev3.py`（整个文件）
- `DMR/Uploader/__init__.py` 里的 `youtubev3` 分支
- `configs/global.yml` 和 `DMR/Config/default.yml` 里的 `youtube` 段
- 顺带把官方的 `custom`（完全自定义上传）段合并进了 `rclone` 段，因为它其实就是
  `engine: subprocess`，功能完全重叠

新增 `upload_args.rclone`：

```yaml
rclone:
  engine: subprocess
  retry: 3
  timeout: 0
  realtime: False          # 整场直播合并成一个视频再传，不产生碎文件
  min_length: 0
  command: ['rclone', 'copy', '{PATH}', '123pan:DMR录播/{TASKNAME}', '--retries', '5']
```

### 4. 【修复】`target` 参数没写时按 engine 自动推断

原版 `DMR/Config/__init__.py` 里，一个 `upload_args` key 展开多份上传时，每份的默认参数
都从 `global.yml` 的 **bilibili** 段继承（`upload_arg.get('target', 'bilibili')` 写死了）。
结果就是"同时传 B站 + 网盘"里网盘那一份会错误地继承 B站的 `realtime: True` 等参数。

现在改成：`target` 没写时，按 `engine` 去 `global.yml` 里匹配同名段；匹配不到才回退到 bilibili。
所以下面两种写法都能正确工作：

```yaml
# 写法一：显式指定 target（推荐）
- target: rclone
  engine: subprocess
  command: [...]

# 写法二：只写 engine，自动识别
- engine: subprocess
  command: [...]
```

### 5. 【修复】`_check_for_upload` 的 IndexError

`DMR/Task/liveevents.py` 里有 `up_videos[0]`，当同组所有分段都短于 `min_length` 时
`up_videos` 是空列表，会抛 `IndexError` 并中断整个上传流程。已加空列表保护。

### 6. 【修复】`GetStreamURL()` 返回 None 时崩溃，报错还看不懂

`DMR/Downloader/stream_downloader.py`：抖音接口在风控/限流/房间状态异常时返回的 JSON 里
没有 `stream_url`，`GetStreamURL()` 就返回 `None`。原版拿到 None 之后继续往下走，在
`'.m3u8' in stream_url` 处抛：

```
TypeError: argument of type 'NoneType' is not iterable
```

这个报错完全看不出是"主播的流地址没取到"。历史日志里出现过 26 次，每次都白丢一段录制。
现在提前判断并抛出可读的错误：

```
主播名: 获取直播流地址失败（GetStreamURL 返回 None），
通常是平台风控/限流或直播间状态异常，稍后会自动重试。
```

上层的重连退避逻辑（`stream_downloader.py` 的 `restart_interval_*`）会照常重试。

### 7. 【改进】rclone 上传现在能看到失败原因
原版 `SubprocessUploader` 直接把子进程 stdout 交给父进程，失败时日志里只有
`Process [...] return code: 1`，完全不知道 rclone 为什么不干活。现在：

- 子进程输出重定向到临时文件（不会因为管道没人读而卡死）
- 失败时把输出尾部 2KB 带进错误信息
- 命令不存在时给出明确提示（例如 `无法启动 rclone: [WinError 2]`）
- 成功时报告耗时，方便确认上传真的在跑

### 8. 【新增】高质量大文件「跳过上传」规则

用途：横屏、高码率、高帧率的录播体积太大，不值得上传（占带宽/占网盘空间）。
命中规则就整组跳过上传（**B站和网盘都不传**）。

**关键点：跳过上传不影响本地文件** ——
原视频照常按 `clean_args` 删除，弹幕版留存（不上传也不删）。

配置在 `configs/global.yml` → `render_args.dmrender.skip_upload_rule`：

```yaml
skip_upload_rule:
  enabled: False           # 总开关，默认关闭
  skip_landscape: True     # 条件1：横屏（宽 > 高）
  skip_bitrate_kbps: 2500  # 条件2：码率 >= 2500 kbps
  skip_fps: 40             # 条件3：帧率 >= 40 fps
  skip_min_matches: 2      # 3 个条件里满足任意 2 个就跳过
```

`skip_min_matches` 的含义：

| 值 | 效果 |
|---|---|
| `1` | 满足任意一个条件就跳过 |
| `2` | **3 个条件里满足任意 2 个就跳过**（当前设置） |
| `3` | 必须三个全满足才跳过 |

**⚠️ 两个必须知道的前提**：

1. **只在 `common_event_args.auto_upload: True` 时才起作用。** 上传没开，规则不会被触发。
2. **`skip_min_matches: 2` 时竖屏也有机会被跳过**：
   竖屏 + 码率≥2500 + 帧率≥40 同样命中 2 项，会跳过上传。
   这部分也符合"体积太大不传"的初衷，但如果你只想跳横屏，看下面的写法。

**只想跳横屏的写法**（把帧率条件关掉，就只剩「横屏 + 高码率」能命中）：

```yaml
skip_upload_rule:
  enabled: True
  skip_landscape: True     # 命中项 1
  skip_bitrate_kbps: 2500  # 命中项 2
  skip_fps: ~              # 关掉帧率条件，消除竖屏被跳过的可能
  skip_min_matches: 2
```

**数据缺失时的行为（fail-open）**：任何一项探测不到（分辨率/码率/帧率），
都**不会**导致跳过，只会在日志里写明原因。宁可多传也不误跳过。

**内部实现要点**：跳过时状态会标成 `upload_skipped` 而不是停在 `ready`。
这是必须的 —— 清理逻辑要求状态为 `uploaded` 才清理，如果只是"不提交上传任务"，
原视频会永远删不掉。`upload_skipped` 被当作"该传的都处理完了"。

**验证脚本**：
```powershell
python tools\test_skip_upload.py        # 规则引擎单测（22 个用例）
python tools\test_skip_upload_flow.py   # 状态机 + 清理联动集成测试
```

### 9. 【文档】`.gitignore` 补上敏感信息

新增忽略 `rclone.conf` 和 `.login_info/`，避免网盘密码和 B站 cookie 被推到 GitHub。

---

## 三、同时上传 B站 + 网盘怎么配

在每个任务 yml（`configs/DMR-<主播名>.yml`）里加一段：

```yaml
common_event_args:
  auto_render: True
  auto_upload: True        # ← 必须打开
  auto_clean: True
  auto_transcode: False

download_args:
  dltype: live
  url: 'https://live.douyin.com/123456'

upload_args:
  dm_video+bilibili+rclone:      # ← key 必须包含视频类型，其余是匹配标签
    - target: bilibili
      engine: biliuprs
    - target: rclone
      engine: subprocess
      command: ['rclone', 'copy', '{PATH}', '123pan:DMR录播/{TASKNAME}', '--retries', '5']
```

**key 的写法规则**：用 `+` 分隔，其中必须包含一个视频类型：
- `src_video` = 原视频 `.mkv`
- `dm_video`  = 弹幕版 `.mp4`

两份上传**并行**执行，谁都不会等谁。

**关于 `auto_clean` 的重要行为**：清理的触发条件是「该视频类型的所有上传都成功」。
所以只要有一份失败（比如网盘传挂了），文件就不会被删 —— 这是有意的保护机制，
去 WebUI 的「失败上传」里重试即可。

---

## 四、自检脚本

`tools/` 下新增了三个可以直接跑的验证脚本：

```powershell
# 综合自检：配置加载 / 参数校验 / GOP 计算 / 真实渲染+关键帧实测 / 上传器
$env:DMR_TEST_VIDEO='F:\某个带弹幕的.mkv'
python tools\selfcheck.py

# 验证「同时上传 B站+网盘」的配置能正确展开
python tools\test_dual_upload.py

# 真实 rclone 上传冒烟测试（会在网盘建临时目录，测完自动清理）
python tools\test_rclone_upload.py
```

另外 `tools/fix_failed_renders_args.py` 用来修复 `.temp/failed_renders.json` 里
保存的坏参数（失败任务的参数是创建时的快照，改 `global.yml` 对它们无效）：

```powershell
python tools\fix_failed_renders_args.py --dry-run   # 先看会改什么
python tools\fix_failed_renders_args.py             # 实际修改（自动备份 .bak）
```

---

## 五、遗留的坑（原版就有，未修改）

1. **`dm_filter.dm_type` 默认只收纯弹幕** —— 这个坑本魔改版已经填了。
   代码 `DMR/Downloader/Danmaku/danmaku.py:130`：
   ```python
   dm_type = self.dm_filter.get('dm_type') or 'danmaku'
   ```
   留空（`~`）等于只收纯文字弹幕，**礼物弹幕会在进入 `dm_template` 之前就被丢掉**，
   所以 `dm_template.gift` 配了也不生效。

   本魔改版设置为 **只收弹幕 + 礼物，不要进场**：
   ```yaml
   dm_filter:
     dm_type: [danmaku, gift]     # all = 什么都收（含 entry 进场，会刷屏）
   ```
   实测：纯弹幕 ✓收 / 礼物 ✓收 / 进场 ✗过滤 / 超级弹幕 ✗过滤

   验证脚本：`python tools\test_dm_type.py`

   > ⚠️ 注意：原版 `F:\123Pan_DanmakuRender` 那边用的是 `dm_type: all`，
   > 会把 entry（进场）也一起收进去，比魔改版多。两边故意不同，别搞混。
2. **B站 cookie 过期后不会提示**，表现为上传一直失败。cookie 在 `./login_info/bilibili.json`。
3. **`.temp/failed_uploads.json` 里的失败上传不会自动重试**，需要去 WebUI 手动点重试。
4. **失败任务列表没有时间戳**，程序重启后这些任务的状态仍然显示为 `rendering`，
   看起来像是"卡住了"，其实只是没跑。
5. **运行中改配置导致任务静默失败**：`engine.py` 里 `Task xxx not exists.`（历史上 56 次）。
   修改/删除/改名 `configs/DMR-*.yml` 后，队列里残留的旧消息会找不到任务而报错。
   改完配置最好重启程序。
6. **DNS 故障时日志会被刷爆**：2026-08-18~19 两天产生了 42,718 条
   `Failed to resolve 'live.douyin.com'`（恒定 ~1600 条/小时），因为重试循环没有退避/熔断，
   两天就把日志写到 20MB/天。原版未修复。
7. **`download.log` 会无限增长**（当前 140MB / 105 万行，其中 100% 是 WARN 级噪音：
   `Non-monotonous DTS` 96 万条、`Unexpected script tag` 4.5 万条，ERROR 为 0）。
   biliup 的子进程输出会一直追加到这个文件，建议定期删除或加日志轮转。

---

## 五点五、历史日志错误分析

完整的错误清单报告见 [`docs/log_error_report.md`](docs/log_error_report.md)（基于原版 127 个日志文件、
39.5 万行、12.8 万条记录分析得出）。核心结论：

**真问题（会导致丢录制）**
- `Stream-gears 异常退出` **1,520 次真实事件**（涉及 50 个主播，Top：饺子 192、呼噜 129、
  我真的不吃土豆 122、七个核桃 108）。主播仍在线时 biliup 子进程死了，该段录制报废。
  会产生 `pyo3_runtime.PanicException: overflow when subtracting durations` —— 是
  biliup 的 Rust 层 bug，抖音流的 `Non-monotonous DTS` 触发的。
  **本魔改版未修复**（这是 biliup 上游的问题），但重连退避逻辑会让它自动续录。
- **抖音 API `KeyError('data')` 6,430 条**：风控/限流时接口不返回 `data`。
  连锁后果之一就是上面第 6 条修的 `NoneType` 崩溃。
- **磁盘写满 `[Errno 28]` 9 条**：会直接中断录制，建议加水位告警。

**噪音（不用管）**
- 弹幕链路的 814 条 error 全部会自愈（`danmaku.py` 自动取消+重建 task），
  只造成弹幕几秒到几十秒空白，视频不受影响。
- `download.log` 的 102 万条 WARN 全是 FLV 解析器常规抖动，零 ERROR。

**平台**：全部错误都来自抖音，B站 0 条 —— 因为所有任务都是抖音直播间。

---

## 六、致谢

原始项目：[SmallPeaches/DanmakuRender](https://github.com/SmallPeaches/DanmakuRender)（GPL-3.0）
感谢 THMonster/danmaku、wbt5/real-url、ForgQi/biliup、ForgQi/stream-gears 的工作。

**本程序仅供研究学习使用！**
