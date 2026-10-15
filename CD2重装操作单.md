# CloudDrive2 重装操作单

> 目的：修复「上传线程停摆」（WebDAV 收文件但传不到百度）
> 疑似原因：上次自动更新未完成，留下 `clouddrive.exe.tmp` 残留

---

## ✅ 已完成的准备工作

**配置已备份**到：

```
F:\_CD2配置备份_20261005\
```

包含 30 个文件 / 32.77 MB：

| 文件 | 作用 |
|---|---|
| `cloudapidata.json` | ★ **云账号配置**（百度网盘登录信息、挂载设置） |
| `clouddriveconf.json` | CD2 账号（187****532@qq.com） |
| `systemsettings.json` | 系统设置（上传线程数、限速等） |
| `webdav_config.json` | WebDAV 设置（端口 19798、路径 /dav） |
| `clouddrive_data.sqlite` | 主数据库 |
| `dir_cache.sqlite` | 云端目录缓存 |
| `config.toml` / `device_token.txt` / `machineid.txt` | 设备标识 |
| `certs/` `copy_tasks/` `log/` `webhooks/` | 子目录 |

**⚠️ 重装后 CD2 会自动读取原配置目录**（它在 `C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2\`），
所以 **账号和设置应该原样保留，不用重新配置**。

---

## 📋 你要做的步骤

### 步骤 1：关闭 CD2 界面和托盘图标

- 右下角托盘找 CD2 图标 → 右键 → **退出**
- 或者先不管，步骤 2 会停服务

### 步骤 2：停服务（我可以帮你做，说一声）

```powershell
Stop-Service CloudDrive2 -Force
```

### 步骤 3：卸载

- **方式 A（推荐）**：控制面板 → 程序和功能 → 找到 **CloudDrive2** → 卸载
- **方式 B**：直接运行 `C:\Program Files\CloudDrive2\unins000.exe`

> 卸载**不会**删除 `C:\Windows\System32\config\systemprofile\Waytech\CloudDrive2\`
> 里的配置（那是 LocalSystem 用户目录，不在安装目录里）。

### 步骤 4：下载最新版并安装

- 官网：https://www.clouddrive2.com/download.html
- 选 **Windows x64** 版本
- 装到默认路径 `C:\Program Files\CloudDrive2\`

> ⚠️ 装之前**确认 `C:\Program Files\CloudDrive2\` 已被清空**（特别是那个
> `clouddrive.exe.tmp`），如果卸载没清干净，手动删掉整个目录。

### 步骤 5：启动并登录 CD2 账号

- 启动 CD2，它会读原配置
- 如果要求登录，用 `187****532@qq.com`
- 检查 **百度网盘** 挂载是否还在（应该自动恢复）

### 步骤 6：告诉我，我来验证

我会跑这个测试：

```powershell
cd F:\DanmakuRender_AutoUp
.\.venv\Scripts\python.exe tools\audit_cloud.py
```

以及一个 10 字节小文件的上传测试，**确认真的能到云端**之后再补传大文件。

---

## 🔄 如果重装后还是不行

**备用方案：改用百度官方 CLI（BaiduPCS-Go）**

DMR 的上传层是通用的（`subprocess_uploader.py` 跑任意命令），不绑定 rclone。
可以改成调用百度官方命令行工具，绕开 CD2 的上传线程。

告诉我，我来配置。

---

## 📌 其他待办（重装完成后一起处理）

| # | 事项 | 说明 |
|---|---|---|
| 1 | 补传 相扑猫 5 个文件 | 1.07 GB，含 emoji，修复后能正常上传 |
| 2 | 补传 vvu 1 个文件 | 122 MB，名字干净，原因未明（日志已轮转） |
| 3 | 删掉 CD2 里的幻影条目 | 修复后那 5 个 `相扑猫💦-*.mp4` 的幻影记录会消失 |

---

## 🗒️ G 盘提醒（你说不用管，仅记录）

```
G:  卷标 Cold   1236 GB 总容量   剩 13 MB
```

本地 NTFS 盘，非 CD2 挂载盘。你说日常不用它，所以不动。
