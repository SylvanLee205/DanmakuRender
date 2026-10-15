# DanmakuRender-5 魔改版

> 基于 [SmallPeaches/DanmakuRender](https://github.com/SmallPeaches/DanmakuRender) `v5` 分支的魔改版，
> 面向「**抖音直播录制 → 弹幕渲染 → 百度网盘归档**」这条流水线做了大量改造与稳定性加固。

一个可以**长期无人值守运行**的直播录制工具：自动监听主播开播 → 录制 → 叠加弹幕渲染 →
上传百度网盘 → 清理本地文件，全流程自动化，并带手机通知与完整的自检/审计工具。

**当前版本：v5.1.0** —— 见 [Releases](https://github.com/SylvanLee205/DanmakuRender/releases)

---

## 目录

- [核心特性](#核心特性)
- [安装](#安装)
- [快速开始](#快速开始)
- [命令行参数](#命令行参数)
- [配置说明](#配置说明)
- [工具集](#工具集)
- [单元测试](#单元测试)
- [与上游的差异](#与上游的差异)
- [常见问题](#常见问题)
- [文档索引](#文档索引)

---

## 核心特性

### 录制与渲染

| 特性 | 说明 |
|---|---|
| **只收弹幕 + 礼物** | 过滤进场/点赞等噪音消息，弹幕文件更干净（`dm_filter.dm_type`） |
| **GOP 交给编码器** | 默认不显式设置关键帧间隔，由 `hevc_qsv` 按场景自适应；需要固定间隔可在配置里启用 |
| **GOP 自动设置**（可选） | `gop_multiplier = N` → 按源帧率算出 `-g`（例：22fps × 8 = 176 帧） |
| **编码器参数校验** | 提前发现"缺 `:v` 流说明符"这类会产出 0 字节文件的错误配置 |
| **0 字节产物保险闸** | 即使 ffmpeg 报成功也校验产物非空，**避免上传空文件 + 误删源视频** |
| **XML 弹幕支持** | B站录播的 `.xml` 弹幕自动转成 `.ass`（来自上游） |

### 上传与清理

| 特性 | 说明 |
|---|---|
| **rclone → 百度网盘** | 用 rclone 子进程上传，替代官方多平台上传器 |
| **跳过上传规则** | 横屏/高码率/高帧率视频整组跳过上传，省带宽和网盘空间 |
| **清理与上传解耦** | 上传失败不影响清理判定，互不阻塞 |
| **安全的清理判定** | 命中跳过规则的文件标记为 `upload_skipped`，不会卡住清理流程 |

### 可靠性（本版重点）

| 特性 | 说明 |
|---|---|
| **状态持久化** | SQLite 状态库记录会话/产物/上传组，**重启后自动对账**（来自上游） |
| **中断录制自动恢复** | 启动时扫描 `.part` 孤儿分段 → 校验可读性 → 配对弹幕 → 改名入库 → **自动渲染上传** |
| **消息路由修复** | 解决"上传成功却记不上账、清理不触发"（来自上游） |
| **恢复判定不依赖 ffprobe** | 改为文件名标记 + 文件大小，更稳（来自上游） |
| **启动自检** | 配置完整性校验 + 关键名字自检，防止"配了但没生效"静默失败 |

### 运维与可观测

| 特性 | 说明 |
|---|---|
| **控制台"信息丰富但整齐"** | 保留全部 INFO，只过滤 engine 的消息字典噪音 |
| **自定义 PROGRESS 日志级别** | 介于 INFO 和 WARNING，突出关键进度 |
| **手机通知** | 开播通知（🟢）+ 启动状态报告（任务名单/网盘状态/磁盘空间） |
| **心跳日志** | 每 30 分钟一行，确认程序活着 |
| **配置保护** | 每天自动快照 + 启动校验 + 一键恢复 |

---

## 安装

### 1. 环境要求

- **Python 3.11+**
- **ffmpeg / ffprobe**（渲染必需，需在 PATH 或配置里指定路径）
- **rclone**（上传百度网盘必需，需自行配置 remote）

### 2. 获取代码

```bash
git clone https://github.com/SylvanLee205/DanmakuRender.git -b v5
cd DanmakuRender
```

或从 [Releases](https://github.com/SylvanLee205/DanmakuRender/releases) 下载源码包。

### 3. 安装依赖

```bash
python -m venv .venv

# Windows
.venv\Scripts\pip install -r requirements.txt

# Linux / macOS
source .venv/bin/activate && pip install -r requirements.txt
```

> `requirements.txt` 里的 `psutil` 只在跑单元测试时需要，DMR 运行时不依赖。

### 4. 配置 rclone（如果用百度网盘）

```bash
rclone config
# 新建一个 remote（类型选 webdav 或相应网盘类型），例如命名为 cd2
```

然后改 `configs/global.yml` 里 `upload_args_task_default.dm_video.command` 的 remote 名。

---

## 快速开始

### 1. 添加一个主播

复制示例配置并改名（`DMR-` 前缀是必须的）：

```bash
cp configs/temp/example-直播录制.yml configs/DMR-主播名.yml
```

编辑 `configs/DMR-主播名.yml`：

```yaml
common_event_args:
  auto_render: true      # 录完自动渲染弹幕
  auto_upload: true      # 渲染完自动上传
  auto_clean: true       # 上传完自动清理本地文件
  auto_transcode: false

download_args:
  dltype: live
  url: 'https://live.douyin.com/123456789'     # ← 改成真实直播间
  output_dir: './直播回放/主播名'
  output_name: '{STREAMER.NAME}-{CTIME.YEAR}年{CTIME.MONTH:02d}月{CTIME.DAY:02d}日{CTIME.HOUR:02d}点{CTIME.MINUTE:02d}分'
```

### 2. 准备全局配置

`configs/global.yml` 是**用户个人配置**，未随仓库发布。请参考 `docs/` 里的说明自行配置。

### 3. 启动

```bash
python main.py            # 正常启动
```

**Windows 一键启动**：双击 `Start_Render.bat`（自带崩溃自动重启守护）。

---

## 命令行参数

```bash
python main.py [选项]
```

| 参数 | 说明 |
|---|---|
| `--quiet [LEVEL]` | 控制台输出级别。不带值 = `info`（推荐）；可选 `progress` / `warning` / `error` / `debug` |
| `--no-console-filter` | 关闭控制台噪音过滤（排查管道问题时用） |
| `--config <路径>` | 指定全局配置文件，默认 `configs/global.yml` |
| `--no_recover` | 关闭启动时的中断录制（`.part`）自动恢复 |
| `--recover_wait` | 恢复过程同步执行（等恢复渲染完再开始录制），默认后台跑 |
| `--recover_min_age <分钟>` | 只恢复最后修改早于 N 分钟的 `.part`（默认 2） |
| `--debug` | 调试模式 |
| `--version` | 查看版本号 |
| `--skip_update` | 跳过版本检查 |

---

## 配置说明

### 目录结构

```
configs/
  global.yml           全局配置（用户个人配置，不随仓库发布）
  DMR-<主播名>.yml      每个主播一个任务配置
  temp/                配置示例模板
```

### 关键配置段

| 配置段 | 作用 |
|---|---|
| `download_args.live` | 录制参数（分段时长、输出命名、弹幕过滤） |
| `download_args.live.dm_filter` | **弹幕过滤**：`dm_type: ['danmaku', 'gift']` 只收弹幕和礼物 |
| `render_args.dmrender` | 渲染参数（编码器、GOP、跳过上传规则） |
| `render_args.dmrender.skip_upload_rule` | **跳过上传规则**（横屏必选模式） |
| `upload_args` | 上传引擎配置（含 rclone） |
| `upload_args_task_default` | **上传规则本体**（`dm_video` → rclone 命令） |
| `clean_args` | 清理规则（延迟、连带删除策略） |
| `state` | 状态库路径（默认 `logs/dmr_state.db`） |
| `recovery` | 启动对账策略（录到一半的产物怎么处理） |

### 弹幕过滤

```yaml
download_args:
  live:
    dm_filter:
      dm_type: ['danmaku', 'gift']   # 只收弹幕 + 礼物（过滤进场/点赞）
      keywords: ~                     # 按关键词过滤
      username: ~                     # 按用户名过滤
      max_length: 0                   # 超长弹幕过滤
```

### 跳过上传规则

```yaml
render_args:
  dmrender:
    skip_upload_rule:
      enabled: true
      skip_landscape: true            # 跳过横屏视频
      skip_require_landscape: true    # 判定依据：必须确认是横屏才跳过
      skip_bitrate_kbps: 2500         # 码率阈值
      skip_fps: 40                    # 帧率阈值
      skip_min_matches: 1             # 命中几条就跳过
```

命中规则的文件会被标记为 `upload_skipped`，**不影响清理流程**（不会被当成"还没处理完"）。

### GOP（关键帧间隔）

```yaml
render_args:
  dmrender:
    gop_multiplier: ~      # ~ = 不干预，用编码器默认（推荐）
    gop_default_fps: 30    # 探测不到帧率时的兜底
    # gop_multiplier: 8    # 每 8 秒一个关键帧（22fps → -g 176）
```

### 状态持久化与恢复

```yaml
state:
  db_path: logs/dmr_state.db

recovery:
  on_interrupted_file: ask    # ask / keep / discard 录到一半的产物
  resume: true                # 重启后自动继续处理未完成的渲染/上传
```

> ⚠️ 状态库是**单一全局库**，以任务名区分。删掉它会丢失所有未完成进度。
> `resume: true` 会把上次没上传/没渲染完的分段接着处理，
> 但**已上传或已清理的产物永不重跑**，不会重复投稿。

---

## 工具集

`tools/` 目录下是运维与审计工具（不影响主程序运行）：

### 诊断与审计

| 工具 | 用途 |
|---|---|
| `feature_audit.py` | 功能完整性 + **接线检查**（含"定义了但没人调用"检测） |
| `full_audit.py` | 全盘配置/功能核对 |
| `check_critical_names.py` | 启动自检：渲染/上传路径的关键名字 |
| `deep_name_scan.py` | 展开 `import *` 递归解析，找未定义名 |
| `audit_cloud.py` | 云端上传审计（找出本地有、云端无的文件） |
| `health_check.py` | 一键健康检查 |
| `regression_check.py` | 部署后功能回归验证 |

### 配置保护

| 工具 | 用途 |
|---|---|
| `backup_configs.py` | 配置快照 / 校验 / 恢复 |
| `prescan.release.py` | 发布前敏感信息扫描 |

### 恢复与清理

| 工具 | 用途 |
|---|---|
| `recover_part.py` | 中断录制（`.part`）恢复 |
| `rerender_after_xml_fix.py` | 重新渲染失败的分段 |
| `clean_sources.py` | 安全清理源文件（带 6 层防护） |
| `compare_duplicates.py` | 比对重名文件是否真重复 |
| `cd2_queue_health.py` | 网盘队列健康维护 |
| `clean_cd2_queue.py` | 清理失败的网盘任务 |

### 运维

| 工具 | 用途 |
|---|---|
| `safe_restart_dmr.py` | 安全重启（重启前检查录制状态） |
| `cleanup_duplicate_streamgears.py` | 彻底停止（含子进程）+ 孤儿分段恢复 |
| `create_release.py` | 创建 GitHub Release |

### 启动自检

主程序启动时会自动跑检查，输出在日志/控制台：

```
配置完整性校验
  ✅ global.yml 关键段完整
  ✅ 任务配置 33 个
  ✅ 与最近快照一致（20261015-190029）
  ✅ 关键名字自检通过（渲染/上传路径正常）
```

---

## 单元测试

内置 **437 个单元测试**（来自上游，零新增运行时依赖）：

```bash
# 先装测试依赖
pip install psutil

# 跑全部测试
python -m unittest discover -s unit_tests -t . -v
```

预期结果：

```
Ran 437 tests in 43s
OK (expected failures=5)
```

---

## 与上游的差异

| 方面 | 上游 | 本版 |
|---|---|---|
| **上传目标** | B站 / YouTube / 自定义 | **rclone → 百度网盘** |
| **弹幕过滤** | 全部收 | **只收弹幕 + 礼物** |
| **跳过上传** | 无 | **横屏/码率/帧率规则** |
| **清理** | 与上传耦合 | **解耦** |
| **通知** | 无 | **开播 + 启动报告** |
| **控制台** | 全量输出 | **降噪但保留 INFO** |
| **启动自检** | 无 | **配置完整性 + 关键名字 + 0 字节保险闸** |
| **工具集** | 基础 | **20+ 运维/审计工具** |
| **文档** | 基础 | **详细排查记录与规范** |

> 本版**移除**了 B站 / YouTube 上传与相关依赖。

---

## 常见问题

### Q: 控制台信息太多看不过来？

```bash
python main.py --quiet=progress    # 只看关键进度和警告
```

或保持默认 `--quiet`（INFO），它已经过滤掉了 engine 的消息字典噪音。

### Q: 改了 `configs/global.yml` 没生效？

**全局配置需要重启程序才生效。** 程序检测到改动后会打印横幅提醒：

```
==========================================================
⚠️  全局配置已更新，但**需要重启程序才会生效**！
    改的是: configs/global.yml
    重启方法: 关闭当前程序（或在终端按 Ctrl+C），
              Start_Render.bat 会自动把它拉起来。
==========================================================
```

> 任务配置（`DMR-*.yml`）支持热加载，改完自动重启对应任务。

### Q: 录到一半程序崩了，文件会丢吗？

不会。重启时会自动扫描 `.part` 孤儿分段，校验可读性 → 配对弹幕 → 改名入库 → 自动渲染上传。

### Q: 渲染失败，源视频会被删吗？

不会。渲染失败不会触发清理。另外有 **0 字节产物保险闸**：即使 ffmpeg 报成功，
产物为空也会被判失败并删除残留，源视频保留。

### Q: 怎么确认云端文件没丢？

```bash
python tools/audit_cloud.py
```

它会对比本地和云端（读网盘缓存），列出本地有而云端没有的文件。

### Q: 配置被误改了怎么办？

```bash
python tools/backup_configs.py list                    # 看有哪些快照
python tools/backup_configs.py verify                  # 校验当前 vs 最近快照
python tools/backup_configs.py restore <快照名>         # 恢复
```

程序每天 04:00 会自动打快照（若已注册计划任务）。

---

## 文档索引

### 使用与规范

- [目录结构说明](README-目录结构.md)
- [控制台日志格式规范](docs/控制台日志格式规范.md)
- [重启通知说明](docs/重启通知说明.md)
- [配置保护机制](docs/配置保护机制.md)
- [测试说明](docs/测试说明-依赖与运行.md)

### 排查记录（真实事故复盘）

- [事故记录：清理静默失败](docs/事故记录-清理静默失败.md)
- [排查记录：上传失败根因](docs/排查记录-20261006-上传失败根因.md)
- [警告：CD2 缓存也有幻影条目](docs/警告-CD2缓存也有幻影条目.md)

### 上游合并与复查

- [上游合并与部署记录](docs/上游合并与部署记录-20261015.md)
- [复查报告](docs/复查报告-20261015.md)

### 环境相关

- [CD2 版本切换记录](docs/CD2版本切换记录-服务版.md)
- [服务版优势与远程访问安全](docs/服务版优势与远程访问安全.md)
- [上传方案备选：BaiduPCS-Go 迁移手册](docs/上传方案备选-BaiduPCS-Go迁移手册.md)

### 上游文档

- [安装文档](docs/installation.md)
- [使用文档](docs/usage.md)
- [更新说明](docs/CHANGELOG.md)
- [项目当前状态](docs/project_state.md)

---

## 致谢

- 上游项目：[SmallPeaches/DanmakuRender](https://github.com/SmallPeaches/DanmakuRender)
- 本版合并了上游 `ab8d3f3`「录制状态持久化与可靠恢复」等提交
