# 更新说明

> 面向使用者。相关文档：
> [项目当前状态](project_state.md) ·
> [维护记录（技术明细）](maintainer-log.md) ·
> [待办清单](TODO.md) ·
> [返回 README](../README.md)

---

## 状态持久化与可靠恢复（重点）

**解决的核心问题**：程序重启后，"哪些分段录完了、传没传、清理没有"不再丢失。

- **新增状态库**（`logs/dmr_state.db`，SQLite）。录制场次、每个分段的产物、上传组
  归属都会落库。首次运行自动创建，默认配置无需修改。
- **重启后自动继续处理**：上次没上传、没渲染完的分段会在启动时被重新送回处理链
  （渲染 → 上传 → 清理），不再需要人工翻找。
- **录到一半的文件不再无人认领**：进程中途退出留下的 `[正在录制]xxx-Part000-*.mkv`
  会在重启时自动**改名**并继续上传。
- **同一场直播仍进同一稿件**：重启后复用已记录的稿件 id，新分段追加为分 P，
  不会把一场直播拆成多个稿件。

**安全边界**

- 已上传 / 已清理的产物**永不重跑**，不会重复投稿。
- 校验未通过的中断产物**不自动处理**，避免上传不完整文件。
- 判定不依赖 ffprobe：文件名带 `[正在录制]` 标记 **且** 大小达标（默认 30MB）即视为正常。
- 若状态库中存在当前配置里没有的任务，程序会**拒绝启动**并给出指引 —— 防止误删历史进度。

**新增配置**（不写则用默认值）

```yaml
state:
  db_path: logs/dmr_state.db

recovery:
  on_interrupted_file: ask      # 录到一半的文件：ask(默认) / keep / discard
  resume: true                  # 重启后是否自动继续处理未完成的产物
  on_unusable_file: skip        # 不满足恢复条件时：skip(默认，保留文件) / discard / ask
  min_valid_size_mb: 30         # 「录到一半的文件是否可信」的大小阈值（MB）
  stale_after: 604800           # 非终态产物超过此时长无进展则抛弃（秒）
```

---

## 修复

### 上传成功却"记不上账"、清理不触发（重要）

B站稿件**已上传成功**，但状态库里大量产物停在"已录制/上传中"，自动清理不再执行。

根因：上传器回包的消息目标缺少 `replay/` 前缀，被引擎**静默丢弃**，
导致"上传完成"事件从未被处理。现已改为**不再依赖该前缀**，并顺带修复：

- 任务名含 `/` 时会被截断；
- 插件名可能被同名任务遮蔽；
- 路由失败时日志缺少发送方与事件名（现可定位）。

### 其他

- **cookies 过期导致上传失败**：上传器实例长期复用，期间重新登录后实例内旧 cookies
  会失效。现改为**每次上传前重新读取** cookies 文件；读取失败保留原 cookies 继续尝试。
- **非实时上传崩溃**：所有分段都短于 `min_length` 时抛 `IndexError`，中断整个事件处理。
- **未清理的文件被当作已清理**：清理状态被无条件设置，导致状态提前释放。
- **引擎在未启动时调用 `stop()` 崩溃**。

---

## 优化

**下载引擎内存占用**（实测数据）

- `Popen` 的管道缓冲参数导致每个子进程多占 **约 190MB** 内存 —— 改为行缓冲。
- ffmpeg 输出队列无上界，生产快消费慢时 10 秒可积压 150 万行、内存 **+800MB** —— 加上界。
- streamlink 日志文件整体读入（56MB 日志峰值 170MB）—— 改为只读尾部，峰值降到 **0.13MB**。

---

## 新增

- **斗鱼登录态取流**：新增 `douyu_watch_cookies`，可获取**长期有效的原画流**
  （不再 5 分钟后失效）。cookies **只用于取流**，开播判断与房间信息始终匿名。
- **XML 弹幕支持**：渲染器与虚拟录制可直接处理 B站格式的 `.xml` 弹幕
  （需额外安装 `dmconvert`；本程序自行录制的 `.ass` 不受影响）。
- **测试基座**：新增 `unit_tests/`（**430+ 用例**，仅用标准库，零新增依赖）。

运行测试：

```bash
python -B -m unittest discover -s unit_tests -t .
```

---

## 配置基准补齐（`DMR/Config/default.yml`）

配置基准（`default.yml`）此前**缺少若干代码已支持的键**，导致这些功能**无法通过配置文件设置**
（键不在基准里就无法被用户配置覆盖）。现已补齐：

- **`download_args.virtual`**：虚拟录制的完整参数段（此前基准里根本没有这一段）。
- **`upload_args.custom.realtime`**：自定义上传**必须启用**，此前基准里缺失，
  照文档配好也会因为该键为空而不生效。
- **`upload_args.bilibili`**：补充 `charging_pay` / `is_only_self` / `hires` /
  `open_subtitle` / `no_disturbance` / `sort_videos` / `epid` / `credits` / `extra_args`
  （主要供 `biliwebapi` 引擎）。
- **`webservice_kernel_args`**：补充 `port` / `host` / `force_login` / `username` / `password`。
  ⚠️ `host` 默认取 **`127.0.0.1`（仅本机）**，而不是 `0.0.0.0`：默认凭据是 `admin/admin`，
  绑定到 `0.0.0.0` 会把管理界面暴露给同网段所有人。如需外部访问请先改密码。
- **`download_args.live.advanced_video_args`**：补充 `max_fn_length` / `min_video_size` /
  `min_video_duration` / `restart_interval` / `streamlink_quality` / `bili_force_origin`。
- **`download_args.live.dm_filter.dm_type`**、**`download_args.live.sync`**。
- **修正键名**：`dmr_engine_args` 曾写 `dynamic_config_path`，而代码读取的是 `config_path`
  —— 按基准改这一项**不会生效**。现已改为 `config_path`。

`configs/global.yml` 与 `default.yml` 现在内容一致，可作为完整配置参考。

---

## 升级注意

1. **无需修改配置**：新增的 `state` / `recovery` 段都有默认值。
2. **首次运行会创建状态库**（`logs/dmr_state.db`）。它记录未完成的进度，
   **删除等同于放弃全部未完成工作**。
3. **旧版本遗留的 `[正在录制]` 残file**：新版会在重启时自动改名并继续上传，无需人工处理。
4. **旧版本因上述路由缺陷卡在"上传中"的记录**：超过 7 天无进展后自动标记为跳过，
   其场次随后回收，同样无需人工干预。
5. **若你改过 `dmr_engine_args.dynamic_config_path`**：该键从未生效，请改用 `config_path`。

---

## 项目更名为 DanmakuRepo（2026-11-02）

项目名从 `DanmakuRender-AutoUp` 改为 **DanmakuRepo**（Danmaku Media Repo，
弹幕媒体归档库）。**缩写仍是 DMR**，因此绝大部分标识符刻意保持不变，
升级不需要改任何配置。

**改了**

- README / 文档叙事、GitHub 仓库名
- Python 类名 `DanmakuRender` → `DanmakuRepo`（17 处引用，纯机械替换）
- 计划任务：`DanmakuRender_Boot` → `DMR_Boot`，`DanmakuRender_SessionWatch` →
  `DMR_SessionWatch`，`DanmakuRender_Desktop` → `DMR_Desktop`，
  `DanmakuRender_云端上传审计` → `DMR_云端上传审计`，
  `DanmakuRender_配置快照` → `DMR_配置快照`
- 登录启动项：`DanmakuRender_AutoUp.cmd` → `DMR_AutoUp.cmd`

**刻意没改**（为了不动生产路径、也为了保留上游合并基准）

| 保留项 | 原因 |
|---|---|
| 代码包名 `DMR/` 与全部 `from DMR...` import | 缩写巧合，改了要动 363 处 import 和 120 个文件 |
| 配置键 `dmr_engine_args` | 三层配置合并的顶层键，改了偏离上游基准 |
| 日志前缀 `DMR-*.log`、桌面脚本 `DMR-*.bat`、任务配置 `DMR-*.yml` | 同上，且都只是缩写 |
| 项目目录 `F:\DanmakuRender_AutoUp` | 约 130 处硬编码路径引用它，改名需停生产 + 移目录 + 全量验证，收益仅为观感 |

**升级注意**

- 如果你**手工**创建过 `DanmakuRender_*` 计划任务，需要按上表改名，
  否则 `Fix_Boot_Task.bat` 会新建一个 `DMR_Boot`，两个开机任务并存会双启动。
- 已有安装的旧任务不会自动迁移，脚本也不会去找旧名字。

---

## 弹幕字符导致整场渲染失败：三个真凶与字形安全清洗（2026-11-02）

**解决的核心问题**：弹幕里出现某些字符时，整场渲染会失败，日志只有一条
`Assertion ((dst_linesize) >= 0 ? (dst_linesize)) >= bytewidth failed at
libavutil/imgutils.c:351`。DMR 自带的「硬件编码失败就降级软件编码」救不了它
—— 根因不在编码器。

排查发现**三个互不相干**的真凶（详见
[排查记录-20261102-渲染崩溃三个真凶.md](排查记录-20261102-渲染崩溃三个真凶.md)）：

1. **无字形字符**：如注音符号「ㄓ」U+3103。系统里一个覆盖它的字体都没装，
   libass 找不到字形就输出异常帧。
2. **彩色 emoji 字体**：国旗指示符 U+1F1E8、🐈🎂🌈 等会回退到 Segoe UI Emoji
   （COLR 彩色字体），libass 对彩色字形位图处理有缺陷，同样触发断言。
3. **源视频损坏帧**：录制的 ts 有丢包时，libass 输出帧的 stride 会算错
   （`width 720 > stride 640`），任何编码器都会拒绝。

**改动**

- 新增 `DMR/Downloader/Danmaku/glyphs.py`：扫系统字体建「可渲染码位表」+
  「彩色字体黑名单」，写 `.ass` 前把危险字符剔掉。判据是
  **主字体没有、彩色字体才有**的码位（主字体有字形就不会触发回退）。
  检测不可用时**原样放行**，不会把弹幕全删。
- `requirements.txt` 增加 `fonttools`（纯 Python）。**升级后需要重新
  `pip install -r requirements.txt`**，否则字形清洗不生效（会打 warning 并跳过）。
- 新增工具 `tools/rename_orphans.py`：把 `[正在录制]` 孤儿分段登记进状态库，
  让启动对账自动改名、渲染、上传。默认只预览，`--apply` 才写库，
  写前自动备份 `.db`。
- `tools/stop_dmr.py` 默认改为**优雅停止**：先请求 DMR 收尾（ffmpeg 收到 `q`，
  写完当前段并改名），最多等 180 秒，超时才硬杀。`--force` 可跳过。

**升级注意事项**

- 改的是 `DMR/` 下代码，**必须重启 DMR 才生效**（配置热加载不覆盖代码）。
- 首次运行会扫一遍系统字体建表（约 5 秒），结果按字体目录指纹缓存到
  `.temp/glyph_coverage.json`；装/删字体会自动重建。
- 已写坏的 `.ass` **不会**回溯清洗。要救某一场，需对该文件跑一次清洗后重渲
  （源 `.ts` 通常还在）。

---

## 已知问题（尚未修复）

| 问题 | 影响 |
|---|---|
| B站弹幕 `uid` 解析后未写入注册包 | 登录态弹幕功能未生效 |
| B站弹幕改写类级共享 `headers` | 跨任务可能污染 |
| `bili_dm_cookies` 无法通过配置设置 | 只能硬编码 |
| `huya_mobile_api` 参数不可配置 | 代码仍透传，配置无此键 |
| 事件注册会覆盖既有处理器 | 多处理器场景静默失效；`render/error` 等键不可达 |
| 清理链路无完成回调 | 无法得知清理是否成功；`auto_clean` 单独开启时清理不执行 |
| **hevc_qsv 硬件编码不稳定** | 长视频渲染有概率失败（2026-11-02 发现）。`-f null`/libx265 均正常，只有它崩；可能与 Arc 蓝屏 `0x113` 同源，**建议更新显卡驱动** |
| 渲染前无「有效内容占比」预检 | 源视频只录到少量内容时仍会白烧时间渲染，最后才被时长校验拒掉 |
| `DMREngine.start()` 非幂等 | 预注册插件后再次启动会抛异常（当前主流程不触发） |
