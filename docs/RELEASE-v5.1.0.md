# DanmakuRender-5 魔改版 v5.1.0

> 基于上游 [SmallPeaches/DanmakuRender](https://github.com/SmallPeaches/DanmakuRender) 的 `v5` 分支，
> 面向"**抖音录播 → 弹幕渲染 → 百度网盘归档**"这条链路做了大量魔改与稳定性加固。

---

## 这个版本是什么

一个**长期无人值守运行**的直播录制工具：自动监听主播开播 → 录制 → 叠加弹幕渲染 →
上传百度网盘 → 清理本地文件，全流程自动化，并带手机通知与完整的自检/审计工具。

---

## 主要特性

### 录制与渲染
- **只收弹幕 + 礼物**：过滤进场/点赞等噪音消息（`dm_filter.dm_type`）
- **GOP 交给编码器默认**：不再显式设置关键帧间隔（可在配置里重新启用）
- **GOP 自动设置**（可选）：`gop_multiplier = N` → 按源帧率计算 `-g`
- **编码器参数校验**：提前发现"缺 `:v` 流说明符"这类会产出 0 字节文件的配置
- **0 字节产物保险闸**：即使 ffmpeg 报成功也校验产物非空，避免上传空文件 + 误删源视频
- **XML 弹幕支持**（来自上游）：B站录播的 `.xml` 弹幕会自动转成 `.ass`

### 上传（百度网盘 / rclone）
- **rclone 子进程上传**：替代官方多平台上传器，直传百度网盘
- **跳过上传规则**：横屏/高码率/高帧率视频整组跳过，省带宽和网盘空间
  - 命中规则的文件标记为 `upload_skipped`，不会卡住清理流程
- **清理与上传解耦**：上传失败不影响清理判定，互不阻塞

### 可靠性（本版重点）
- **状态持久化**（来自上游）：SQLite 状态库记录会话/产物/上传组，重启后自动对账
- **中断录制自动恢复**：启动时扫描 `.part` 孤儿分段，校验可读性 → 配对弹幕 →
  改名入库 → 自动渲染上传
- **消息路由修复**（来自上游）：解决"上传成功却记不上账、清理不触发"
- **恢复判定不依赖 ffprobe**：改为文件名标记 + 文件大小，更稳

### 运维与可观测
- **控制台"信息丰富但整齐"**：保留全部 INFO，只过滤 engine 的消息字典噪音
- **自定义 PROGRESS 日志级别**：介于 INFO 和 WARNING，突出关键进度
- **启动自检**：
  - 配置完整性校验（关键段 + 与快照比对）
  - 关键名字自检（防"用了但拿不到"导致渲染/上传静默失败）
- **手机通知**：开播通知（🟢）、启动状态报告（含任务名单/网盘状态/磁盘空间）
- **心跳日志**：每 30 分钟一行，确认程序活着
- **配置保护**：每天自动快照 + 校验 + 一键恢复

### 工具集（`tools/`）
| 工具 | 用途 |
|---|---|
| `feature_audit.py` | 功能完整性 + 接线检查（含"定义了但没人调用"检测） |
| `full_audit.py` | 全盘配置/功能核对 |
| `check_critical_names.py` | 启动自检：渲染/上传路径的关键名字 |
| `deep_name_scan.py` | 展开 `import *` 递归解析，找未定义名 |
| `backup_configs.py` | 配置快照 / 校验 / 恢复 |
| `clean_sources.py` | 安全清理源文件（带 6 层防护） |
| `compare_duplicates.py` | 比对重名文件是否真重复 |
| `safe_restart_dmr.py` / `cleanup_duplicate_streamgears.py` | 安全重启 |
| `recover_part.py` | 中断录制恢复 |
| `audit_cloud.py` | 云端上传审计 |

---

## 单元测试

内置 **437 个单元测试**（来自上游，零新增运行时依赖）：

```bash
python -m unittest discover -s unit_tests -t .
# Ran 437 tests, OK (expected failures=5)
```

> 跑测试需要额外装 `psutil`（测试依赖，DMR 运行时不依赖）——
> 已加入 `requirements.txt` 并注明。

---

## 安装

```bash
git clone https://github.com/SylvanLee205/DanmakuRender.git -b v5
cd DanmakuRender
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt     # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # Linux/macOS
```

需要额外准备：
- **ffmpeg / ffprobe**（渲染必需）
- **rclone**（上传百度网盘必需，需自行配置 remote）

## 快速开始

1. 复制 `configs/temp/example-直播录制.yml` 到 `configs/DMR-<主播名>.yml`，填入直播间 URL
2. 按需修改 `configs/global.yml`（上传/渲染/清理参数）
3. 运行 `python main.py`（或 Windows 下双击 `Start_Render.bat`）

常用参数：
```bash
python main.py --quiet              # 控制台保留 INFO，过滤引擎噪音（推荐）
python main.py --quiet=progress     # 只看关键进度和警告
python main.py --no_recover         # 关闭启动时的中断录制恢复
python main.py --version            # 查看版本
```

---

## 与上游的差异摘要

| 方面 | 上游 | 本版 |
|---|---|---|
| 上传目标 | B站 / YouTube / 自定义 | **rclone → 百度网盘** |
| 弹幕过滤 | 全部收 | **只收弹幕 + 礼物** |
| 跳过上传 | 无 | **横屏/码率/帧率规则** |
| 清理 | 与上传耦合 | **解耦** |
| 通知 | 无 | **开播 + 启动报告** |
| 控制台 | 全量输出 | **降噪但保留 INFO** |
| 自检 | 无 | **配置完整性 + 关键名字** |
| 工具集 | 基础 | **20+ 运维/审计工具** |
| 文档 | 基础 | **详细排查记录与规范** |

> 本版**移除**了 B站 / YouTube 上传与相关依赖。

---

## 注意事项

- ⚠️ `configs/` 是配置的唯一真实来源，**请自行备份**（本版带自动快照工具）
- ⚠️ 本版面向**抖音**录制优化；B站/斗鱼/虎牙相关路径保留但未重点验证
- ⚠️ 状态库 `logs/dmr_state.db` 是单一全局库，按任务名区分；删除会丢失未完成进度

## 致谢

- 上游项目：[SmallPeaches/DanmakuRender](https://github.com/SmallPeaches/DanmakuRender)
- 本版合并了上游 `ab8d3f3`「录制状态持久化与可靠恢复」等提交

---

**完整改动记录见 [`docs/`](docs/) 目录**，包括：
- `上游合并与部署记录-20261015.md`
- `复查报告-20261015.md`
- `配置保护机制.md`
- `事故记录-清理静默失败.md`
- `控制台日志格式规范.md`
