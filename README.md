# DanmakuRender-AutoUp

**无人值守的直播录播服务器。** 多路并发录制 → 弹幕渲染 → 网盘上传 → 自动清理，
7×24 跑着，不需要人盯。

基于 [SmallPeaches/DanmakuRender](https://github.com/SmallPeaches/DanmakuRender) **v5**
深度定制的**生产演进版**。原版解决的是"怎么录"，这个版本解决的是
**"怎么无人值守地录上一年不出事"**。

- 目前实盘：**33 个主播**同时监控，抖音为主，已连续运行数月
- 一场直播从开播到下播全程自动：录制 → 渲染弹幕版 → 上传网盘 → 24 小时后删源视频
- 崩溃能自愈：开机自启、会话迁移、优雅停止、启动对账补派
- 有 **503 个模块级测试**兜底

> ### 🚀 刚接手这个项目？
> **先读 [`docs/交接.md`](docs/交接.md)** —— 30 分钟通读，包含：
> 怎么跑起来、日常操作、**踩坑 Top 10**（前五个都实际造成过事故）、
> 出事了的急救表、完整文档导航。不需要任何背景知识。

---

## 一、它和原版最大的不同

原版的架构（引擎/消息/插件/配置合并/下载器抽象）**完整保留**，
改掉的全是外围。完整清单见
[`docs/与上游的差异.md`](docs/与上游的差异.md)。

| 方面 | 原版 | 这里 |
|---|---|---|
| **上传** | B站（biliup） | **rclone → 百度网盘**，可跳过横屏高码率 |
| **清理** | 基本没有 | 延迟清理（默认 24h）+ 后悔期 + 状态库记录 |
| **状态** | 重启即丢 | **SQLite 状态库**，重启后自动补渲染/补上传/补清理 |
| **运维** | 手动启动 | 开机自启三层、优雅停止、启动对账、孤儿分段自动接管 |
| **可观测性** | 日志 | 心跳、自检脚本、`tools/dmr-status.ps1` 面板 |
| **测试** | 无 | 503 个 unittest，含状态库/清理/自启/字形清洗 |
| **文档** | 安装+使用 | 另有排查记录、维护记录、与上游差异、项目状态 |

**为什么不再跟上游合并**：上游最后一次提交是 2026-10-10（状态持久化），
我们 10-15 就合并过了，之后至今无更新；且上游无 LICENSE 文件，
没有 Copyleft 义务。详见
[`docs/与上游的差异.md`](docs/与上游的差异.md#为什么不再跟上游合并)。

---

## 二、快速开始

```bash
# 1. 装依赖（注意：比原版多了 rclone/psutil/fonttools）
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt

# 2. 装 ffmpeg（放进 tools/ 或加入 PATH）

# 3. 启动
Start_DMR.bat          # Windows 一键启动（守护循环，崩了 10 秒自重拉）
```

日常**只需要两个操作**：

```bash
# 加主播：复制抖音直播间链接，然后
DMR-添加主播.bat        # 读剪贴板 → 自动取名 → 写 configs/ → 热加载，不用重启

# 看状态
DMR-看实时日志.bat      # 滚动日志 + 定期状态行
```

停用某个主播：把 `configs/DMR-xxx.yml` 挪进 `configs/temp/`，
再跑 `tools/purge_task_state.py --apply`（只挪配置会让 DMR 拒绝启动，
这是设计好的保护，详见 [`docs/project_state.md`](docs/project_state.md)）。

---

## 三、运维工具（原版没有，这是最值钱的部分）

全部在 `tools/`，**默认都是预览模式，加 `--apply` 才真动手**：

| 工具 | 干什么 |
|---|---|
| `add_room.py` | 读剪贴板链接，自动取名写配置，热加载 |
| `stop_dmr.py` | **优雅停止**：ffmpeg 收到 `q` 写完当前段并改名，超时才硬杀 |
| `autostart_launch.py` | 登录自启 + 跨会话迁移（窗口跟着人走） |
| `rename_orphans.py` | 把 `[正在录制]` 孤儿分段登记进状态库，让启动对账自动接管 |
| `clean_skipped_backlog.py` | 清"命中跳过上传规则却永不清理"的积压源视频 |
| `purge_task_state.py` | 清停用任务的状态库记录（先备份 .db） |
| `sync_full_backup.py` | 同步完整副本（含 configs/）到私有仓库 |
| `dmr-status.ps1` | 状态面板：进程、会话位置、窗口可见性、自动登录有效性 |
| `post_boot_check.py` | 重启后自检：自动登录四要素、DMR 起在哪个会话 |

---

## 四、目录结构

```
DMR/                     核心代码（架构沿用原版）
  ├── state/             SQLite 状态库 + 启动对账（新增）
  ├── Task/liveevents.py 录制事件处理、上传/清理判定（改动最大）
  ├── Cleaner/           延迟清理（新增）
  ├── Downloader/        下载器；Danmaku/glyphs.py 是字形安全清洗（新增）
  └── Config/            配置合并（原版）
tools/                   运维工具（见上，几乎全是新增）
unit_tests/              503 个模块级测试（新增）
configs/                 任务配置（DMR-*.yml）+ temp/ 停用归档区
docs/                    文档（见下）
直播回放/                 按主播分目录，弹幕版在「（弹幕版）」子目录
```

---

## 五、文档索引

### 第一站
- [**交接文档**](docs/交接.md) —— **刚接手先读这个**。怎么跑、怎么动手、
  踩坑 Top 10、出事急救表、完整导航。不需要任何背景。

### 面向使用者
- [安装文档](docs/installation.md) —— 环境准备与安装步骤
- [使用文档](docs/usage.md) —— 配置项与各项功能的使用说明
- [更新说明](docs/CHANGELOG.md) —— 每个版本改了什么、升级注意事项
- [与上游的差异](docs/与上游的差异.md) —— **我们改了什么、为什么、为什么不再合并**

### 面向开发者
- [项目当前状态](docs/project_state.md) —— 核实过的架构事实、产物语义、关键决策
- [维护记录](docs/maintainer-log.md) —— 已完成工作的技术明细（根因、实现、踩坑与教训）
- [待办清单](docs/TODO.md) —— **仅记录未完成事项**与已确认的缺陷
- [测试说明](unit_tests/README.md) —— 模块级测试的组织与运行方式

### 故障排查记录（生产环境实盘事故）
按时间倒序。每条都写了**错误的排查方向**——那往往比正确结论更有价值。

- [2026-11-02 渲染崩溃三个真凶](docs/排查记录-20261102-渲染崩溃三个真凶.md) ——
  同一条 ffmpeg 断言背后是三个独立故障：无字形字符 / 彩色 emoji 字体 /
  源视频损坏帧导致 libass 输出帧 stride 算错。附「分层验证」方法与判据演进。
- [2026-10-06 上传失败根因](docs/archive/排查记录-20261006-上传失败根因.md) ——
  路由器限速填错单位（4 Mbps 应为 35 Mbps），排查方向全错的故事。

### 归档（[`docs/archive/`](docs/archive/)，21 篇）
历史快照、一次性报告、CD2/网盘运维专题。按需查，不必通读 ——
清单与每篇的内容说明见[交接文档第七节](docs/交接.md#七文档导航)。

### 测试
本仓库自带模块级测试，运行方式：

```bash
python -B -m unittest discover -s unit_tests -t .
```

> `-B` 用于避免本仓库 `__pycache__` 的写入权限问题（见 `TODO.md` B6）。

需要按**当前配置**做一次完整流程冒烟（180 秒后自动停止任务）：

```bash
python dryrun.py
```

---

## 六、分支与仓库

| 分支 / 仓库 | 内容 |
|---|---|
| `prod-sync`（默认） | **生产环境代码** |
| `v5` | 上游发布版基线，已脱敏（无内网地址、示例配置） |
| 私有仓库 `DanmakuRender-Full` | 完整副本（含 `configs/`、状态库），灾难恢复用。含主播链接等敏感信息，**请勿公开** |

本地 `master` 保留完整提交历史；`prod-sync` 是脱敏后的同步分支。

---

## 七、致谢

原版与依赖：

- [SmallPeaches/DanmakuRender](https://github.com/SmallPeaches/DanmakuRender) ——
  本项目的 base，引擎/消息/插件架构全部来自它
- THMonster/danmaku、wbt5/real-url、ForgQi/biliup、ForgQi/stream-gears
- ffmpeg / libass / rclone / fontTools / psutil

**本程序仅供研究学习使用！**
