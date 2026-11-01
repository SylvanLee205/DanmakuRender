# CD2 版本切换记录：应用版 → 核心服务版

**切换日期**：2026-10-06
**切换原因**：用户偏好服务版（跑在 Session 0，不弹控制台窗口；Windows 服务自带自愈）

---

## 一、两个产品到底有什么区别

⚠️ **最容易搞混的地方**：两者的进程名都叫 `clouddrive.exe`，
`Get-Process CloudDrive` 会同时匹配两个。必须看**路径**区分。

| | **核心服务版** | **应用版** |
|---|---|---|
| 安装目录 | `C:\Program Files\CloudDrive2\` | `C:\Program Files\CloudDrive\` |
| 主程序 | `clouddrive.exe`（22.3 MB） | `CloudDrive.exe`（0.3 MB，实际是 WinUI 壳） |
| 启动方式 | `shawl.exe run --no-log -- clouddrive.exe` | 直接运行，`--autostart` |
| 运行账户 | **LocalSystem (SYSTEM)** | 当前登录用户 |
| 会话 | **Session 0**（无桌面） | 用户会话（有桌面） |
| 开机自启 | Windows 服务（AUTO_START） | HKCU Run 键 |
| WebDAV 端口 | **19798** | **29798** |
| 配置目录 | `C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2\` | `%LOCALAPPDATA%\CloudDrive.WinUI\` |
| 失败自愈 | ✅ **服务自带**（已配 5s/15s/60s 重启） | ❌ 需要外部看门狗 |
| 控制台窗口 | ✅ 不弹（Session 0） | ✅ 不弹（GUI 程序） |
| 健康检查 | `http://127.0.0.1:19798/` | `http://127.0.0.1:29798/` |

**两者功能等价**：同一个百度账号、同一个 `/百度网盘` 目录、都开 `webdav_root = "/"`。

## 二、切换步骤（已完成）

```
1. 启动服务版并设为自动启动
   Set-Service CloudDrive2 -StartupType Automatic
   Start-Service CloudDrive2

2. 验证服务版 WebDAV 能读云端
   → exit=0，读到 15 个目录 ✅

3. ★ 验证服务版能真的上传（关键，不能只看 rclone 的 exit=0）
   上传 2MB 测试文件 → 查服务版 dir_cache.sqlite 确认条目存在
   → ✅ 成功，日志 0 条 PermissionDenied

4. 改 rclone 指向 19798
   C:\Users\Administrator\AppData\Roaming\rclone\rclone.conf
   [cd2]
   url = http://localhost:19798/dav        ← 原来是 29798

5. 停掉应用版
   taskkill /F /IM CloudDrive.exe
   （注意：进程名相同，别误杀服务版的 clouddrive.exe）

6. 关闭应用版开机自启
   Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'CloudDrive'
   （原值备份在 .temp\cd2_app_autostart_backup.txt）

7. 配置服务版失败自动重启
   sc.exe failure CloudDrive2 reset= 86400 actions= restart/5000/restart/15000/restart/60000

8. 删除 CD2 看门狗
   Unregister-ScheduledTask -TaskName 'DanmakuRender_CD2守护'
   （服务版自带自愈；而且看门狗只会去启动应用版，反而会打架）
   任务定义备份在 .temp\cd2_watchdog_task_backup.xml
   静默启动器 tools\run_watchdog_hidden.vbs 已删除

9. 服务版配置优化
   file_log_level: Error → Info
     （Error 级别会隐藏关键诊断信息。2026-10-05 那次 8427 次 errno -7
       疯狂重试只留下寥寥几条日志，就是 Error 级别造成的）
   max_upload_speed_kbyps: 4096 → 0
     （对 WebDAV 上传本来就无效，实测设 4096 后峰值仍 6.79 MB/s）
   备份在 F:\_CD2配置备份_20261005\svc_before_opt_233824\
```

## 三、切换后的架构

```
DMR (Python)
  └─ subprocess: rclone copy
       └─ WebDAV → http://localhost:19798/dav
            └─ 核心服务版 CloudDrive2 (SYSTEM, Session 0, 服务自愈)
                 └─ 百度网盘 /百度网盘/DMR录播/<任务名>/
```

## 四、验证结果

```
服务版:            Running / Automatic
19798 监听:        2 个
应用版 29798:      无监听 ✅
应用版开机自启:    已移除 ✅
看门狗任务:        已删除 ✅
rclone 读云端:     exit=0，15 个目录 ✅
端到端上传测试:    ✅ 成功（PermissionDenied: 0）
```

## 五、回滚方法（如果服务版出问题）

```powershell
# 1. rclone 改回 29798
notepad "$env:APPDATA\rclone\rclone.conf"
#   把 url 改成 http://localhost:29798/dav

# 2. 启动应用版
Start-Process 'C:\Program Files\CloudDrive\CloudDrive.exe' -ArgumentList '--autostart'

# 3. 恢复应用版开机自启（原值在 .temp\cd2_app_autostart_backup.txt）
Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' `
  -Name 'CloudDrive' -Value '"C:\Program Files\CloudDrive\CloudDrive.exe" --autostart'

# 4. 恢复看门狗（定义在 .temp\cd2_watchdog_task_backup.xml）
Register-ScheduledTask -TaskName 'DanmakuRender_CD2守护' -Xml (Get-Content .temp\cd2_watchdog_task_backup.xml -Raw)

# 5. 停掉服务版
Stop-Service CloudDrive2
Set-Service CloudDrive2 -StartupType Disabled
```

**应用版没卸载**，所以回滚随时可以。

## 六、为什么当初误判"服务版上传线程坏了"

2026-10-05 排查时看到服务版日志里有 **8427 次 `errno: -7` 疯狂重试**，
当时结论是"服务版上传能力有问题，所以用应用版"。

**这是错的。** 真实原因是：rclone 配置指向 `localhost:19798`（服务版端口），
但**当时服务版是停的**，实际在跑的是应用版（29798）。
所以 rclone 要么连不上、要么行为混乱。

**教训：两个产品的端口不同、配置目录不同、进程名相同。**
排查时**必须先确认"哪个实例在跑、rclone 指向哪个端口"**，否则会得出完全错误的结论。

## 七、日常维护

```powershell
# 服务状态
Get-Service CloudDrive2

# 端口/健康
Invoke-WebRequest http://127.0.0.1:19798/dav   # 401 = 正常

# 失败自动重启配置
sc.exe qfailure CloudDrive2

# 手动重启服务
Restart-Service CloudDrive2 -Force

# 服务版日志
C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2\log\<日期>.log
```

**服务版仍有的已知限制**（与应用版相同，是 CD2 本身的）：
- 自带 `max_upload_speed_kbyps` 对 WebDAV 上传无效 → 限速要靠路由器
- 永久失败的任务（emoji 文件名 `errno -7`、重复上传）会无限重试占死单线程
  → 用 `tools\cd2_queue_health.py --clean` 清理
- WebDAV 会列出"已接收未上传成功"的幻影条目 → 审计必须查
  `dir_cache.sqlite`，不能用 `rclone lsf`（`tools\audit_cloud.py` 已改）
