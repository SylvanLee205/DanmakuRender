# 上传方案备选：BaiduPCS-Go 迁移手册

> **这份文档是"备用方案"，等 CD2 再次出问题时才启用。**
> 记录时间：2026-10-06
> 起因：CD2 应用版运行 30+ 小时后进程消失，导致上传静默失败数小时。
>      已加看门狗兜底（每 5 分钟检查，5 秒拉起）。先观察，不急于切换。

---

## 一、为什么要考虑它

### CD2 的两个硬伤（都是实测确认的）

| 问题 | 实测证据 |
|---|---|
| **上传限速对自己的 WebDAV 路径无效** | 设 `max_upload_speed_kbyps=4096` 后实测峰值仍 6.79 MB/s。又试了 rclone `--bwlimit`（只限住本地那一跳）和 Windows QoS（注册表值正确但压不住）—— **三种方案全失败** |
| **进程会消失，且没人知道** | 2026-10-05 20:34~22:24 之间进程消失，之后 2 小时上传全部 `connection refused`。DMR 重试 3 次后放弃，静默失败 |

### BaiduPCS-Go 的优势（已核实项目状态）

```
仓库     : github.com/qjfoidnh/BaiduPCS-Go
Star     : 5,699
最后更新 : 2026-09-09（活跃）
最新版   : v4.0.2 (2026-08-21)
许可     : Apache-2.0
Windows  : BaiduPCS-Go-v4.0.2-windows-x64.zip (5.4 MB)
```

1. **上传限速真正可用**（README L950 明确支持单位后缀）：
   ```bash
   BaiduPCS-Go config set -max_upload_rate 4MB/s
   ```
2. **无状态**：调用一次传一次，传完退出 —— **没有"常驻进程崩溃"这个概念**
3. **上传策略丰富**：`--policy rsync`（跳过大小未变的）、`--norapid`、同名自动跳过

### ⚠️ 但要清楚：它不是官方工具

**百度没有官方 CLI。** 网上有传言说百度 2026-04 出过官方 CLI，但无法验证，
主流说法是[百度网盘没有原生命令行工具](https://cloud.tencent.cn/developer/article/2729778)。
BaiduPCS-Go 是**第三方开源**项目，风险是百度改 API 就可能失效（但它活跃维护，风险可控）。

---

## 二、迁移步骤

### 步骤 1：下载

```
https://github.com/qjfoidnh/BaiduPCS-Go/releases/latest
选 BaiduPCS-Go-v4.0.2-windows-x64.zip
```

解压到 `C:\User Program Files\BaiduPCS-Go\BaiduPCS-Go.exe`（和 rclone 放一起，同一层级风格）。

### 步骤 2：登录（推荐 Cookies 方式）

README 明确说**交互式 login 已长期不维护**，推荐 Cookies：

```bash
BaiduPCS-Go login -cookies="你从浏览器复制的完整 Cookie 串"
```

Cookie 获取方法：浏览器登录 pan.baidu.com → F12 → Network → 任意请求 →
复制请求头里的 `Cookie` 整串。

> 也可以 `-bduss=<BDUSS> -stoken=<STOKEN>`，但 STOKEN 必须在**百度网盘页面**获取。

验证登录成功：
```bash
BaiduPCS-Go who
```

### 步骤 3：设置限速和并发（**这是迁移的主要目的**）

```bash
BaiduPCS-Go config set -max_upload_rate 4MB/s
BaiduPCS-Go config set -max_parallel 1
```

> README L952 提醒：普通用户 `max_parallel` 和 `max_download_load` 都要设 1，
> 调大线程只会短时间提速，且极易触发限速。

### 步骤 4：测试上传（用测试目录，别碰生产）

```bash
# 造个测试文件
BaiduPCS-Go upload "C:\temp\test.bin" /DMR录播/__pcs_test__

# 确认到云端
BaiduPCS-Go ls /DMR录播/__pcs_test__

# 清理
BaiduPCS-Go rm /DMR录播/__pcs_test__/test.bin
```

**同时观察网络上行是否被压到 4 MB/s**（用 `Get-NetAdapterStatistics` 采样）。

### 步骤 5：改 DMR 上传命令

编辑 `F:\DanmakuRender_AutoUp\configs\global.yml` 的 `upload_args_task_default.dm_video`：

```yaml
upload_args_task_default:
  dm_video:
    - target: rclone
      realtime: true
      min_length: 0
      engine: subprocess
      retry: 3
      timeout: 0
      # 把 command 换成 BaiduPCS-Go
      command: ['C:\User Program Files\BaiduPCS-Go\BaiduPCS-Go.exe',
                'upload', '{PATH}', '/DMR录播/{TASKNAME}']
```

**注意**：
- `{PATH}` 是本地完整路径，`{TASKNAME}` 是任务名
- BaiduPCS-Go 的目标路径用 **Unix 风格**（`/DMR录播/xxx`），不是 `cd2:` 那种 remote 写法
- **改完必须重启 DMR** 才生效
- ⚠️ BaiduPCS-Go 遇到同名文件**默认跳过**，不会覆盖。要覆盖需配 `upload_policy`

### 步骤 6：验证

```bash
cd F:\DanmakuRender_AutoUp
.\.venv\Scripts\python.exe tools\verify_all_fixes.py    # 确认其它修复没被破坏
.\.venv\Scripts\python.exe tools\audit_cloud.py         # 审计云端
```

### 步骤 7：CD2 怎么处理

- **只做挂载**：保留（但你不挂载，所以用不到）
- **上传已交给 BaiduPCS-Go** → CD2 可以不启动
- 如果确认不再需要，把看门狗计划任务 `DanmakuRender_CD2守护` 停掉

---

## 三、迁移前必须想清楚的风险

| 风险 | 缓解 |
|---|---|
| 第三方项目失效（百度改 API） | 保留 CD2 配置和 rclone 配置，随时能切回去 |
| Cookies 会过期 | BaiduPCS-Go 有刷新机制；失效时重新 `login -cookies=` |
| 上传逻辑和 CD2 不同（无异步缓存） | 上传是同步的，rclone/DMR 的超时设置要相应调整 |
| 文件名仍可能被百度拒绝 | 我们的 emoji 清洗在上传层（`safe_remote_name`），走 subprocess 路径仍然生效 |

**回滚方法**：把上面的 `command` 改回
`['rclone', 'copy', '{PATH}', 'cd2:百度网盘/DMR录播/{TASKNAME}', '--retries', '5', '--low-level-retries', '10', '--transfers', '1']`
并重启 DMR。rclone 配置从未改过，所以回滚只需改一行。

---

## 四、触发切换的条件

**出现以下任一情况，就切 BaiduPCS-Go：**

- [ ] CD2 看门狗日志里出现**第 2 次**拉起记录（说明它反复崩）
- [ ] 审计发现新的"本地有云端无"文件，且原因是上传失败
- [ ] 你决定要严格限速（路由器不好设或设不了）
- [ ] CD2 更新后仍有同样问题

**如果 7 天内看门狗日志一直干净 → 说明 CD2 只是偶发，保持现状即可。**
