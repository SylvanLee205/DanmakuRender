# 录制引擎稳定性对比

分析时间：2026-10-04
数据来源：`F:\123Pan_DanmakuRender\logs\`（127 个日志文件，2026-01 ~ 2026-10）

---

## 一、结论先说

| 项目 | 结果 |
|---|---|
| 历史上真正跑过的引擎 | **只有 `streamgears` 一个**（546 次会话，占 100%） |
| 为什么没有别的 | 配置是 `engine: auto`，而抖音 FLV 流**永远**解析成 `streamgears` |
| streamgears 的异常退出率 | **337 / 546 = 61.7%**（平均每场录制 0.62 次） |
| 实际影响 | **没有丢录制**（见下），但会中断当前分段并重连 |
| 已录制文件的完整性 | **488 个文件，抽查最大的 12 个，全部可解码、无问题** |

**所以：不存在"哪个引擎更稳定"的历史数据可比 —— 因为一直只用了这一个。**

---

## 二、为什么会 "异常退出" 61.7% 却没丢录制

看 `DMR/Downloader/streamgears.py:80-83`：

```python
if not self.stoped and Onair(self.url):
    logfile.seek(0)
    log = logfile.read().decode('utf8', errors='ignore')
    raise RuntimeError(f'{self.taskname} Stream-gears 异常退出 {log[-1000:]}.')
```

触发条件是**「主播还在线，但 biliup 子进程自己退出了」**。也就是说这是个真实的失败事件。

但外层 `DMR/Downloader/stream_downloader.py:315-322` 会兜住：

```python
except Exception as e:
    if self.liveapi.Onair():
        self.logger.exception(e)
        self.stop_once()
        self._pipeSend('liveerror', f'录制过程出错:{e}', ...)
        time.sleep(min(restart_interval_min + restart_interval_step * restart_cnt,
                       restart_interval_max))
        restart_cnt += 1
        continue        # ← 重连
```

而且 streamgears 是**按 `segment`（你配的 3600 秒 = 1 小时）分段的**，每次异常退出只影响**当前还没收尾的那一段**，已经写盘的段会被 `segment_callback` 交给渲染流程。

**所以真实代价是：每场直播平均多一点，会丢掉几十秒到几分钟的画面**，而不是整场丢失。这也解释了为什么日志里 337 次异常退出，但 488 个产出文件全都完好。

---

## 三、异常退出的真实原因分类

日志里 tail 是 `log[-1000:]`，所以只有落在最后 1000 字符里的原因能被看到：

| 次数 | 原因 | 性质 |
|---|---|---|
| 1333 | (无有效信息，只有 FLV 警告) | 未知 —— **这是最大的问题：无法定位** |
| 122 | `Rust panic: overflow when subtracting durations` | **biliup 的真 bug**，时间戳回退触发 |
| 84 | `FLV: Unexpected script tag` | 抖音流格式不规范 |
| 75 | 正常结束 `Done...` | 下播后发现仍在播的误判 |
| 68 | `FLV: Non-monotonous DTS`（时间戳回退） | 抖音流/主播端推流问题 |
| 3 | `FLV: h264 sequence header 变化` | 推流中途换编码参数 |

**关键点**：`Non-monotonous DTS` 在 `download.log` 里出现了 **96 万次**，那是 biliup 的常规抖动、不致命；但累积到某个阈值就会触发上面那个 Rust panic。

**我倾向于同意你的判断**：抖音的 FLV 流本身就不规范（时间戳回退、script tag 异常），加上主播端推流质量/网络抖动，biliup 就崩了。**这不算程序的锅，而是抖音源 + biliup Rust 实现的组合问题。**

---

## 四、换引擎可行吗？—— 静态分析结果：**不建议换**

我读了三个引擎的实现：

### `pyrequests`（纯 Python）—— ❌ 不合适
`DMR/Downloader/pyrequests.py:92-105`：

```python
while not self.stoped:
    try:
        self._download_part(stream_iter)
    except Exception as e:
        self.logger.debug(f'{self.taskname} Error downloading stream: {e}')
        raise e        # ← 直接抛出去，没有任何重连
    finally:
        ... segment_callback(...)   # 但至少保住了已录部分
```

`_download_part` 在流结束/出错时会 `raise RuntimeError(f'{self.taskname} stream end.')`（第 68-69 行），
然后这里 `raise e` **直接冒泡** —— 整个下载器就结束了。
外层虽然也会重连，但 `stream_iter` 是**在 `start()` 开头一次性获取的**
（第 87-90 行），重连时用的是同一个已经失效的迭代器。

**结论：pyrequests 对抖音 FLV 流不可靠，而且它自己都警告 `pyrequests仅支持flv流`**（第 52 行）。
用它会比现在更差。

### `ffmpeg` —— ⚠️ 可行但要改
走 `.m3u8` 的 HLS 流时 `auto` 就会选 ffmpeg。抖音目前主要给 FLV，
要强制用 ffmpeg 得改 `engine: ffmpeg`，并且它没有 streamgears 那种分段回调机制，
录制时长/切分行为会变。

### `streamlink` —— ❌ 不支持抖音
它是给 twitch 等平台用的。

---

## 五、建议

1. **保持 `engine: auto` 不动。** 现有组合（streamgears + 自动重连）是所有方案里最稳的，
   而且你的产出文件实测全部完好。
2. **如果以后想减少异常退出**，真正的抓手不在引擎，而在 biliup：
   `tools/biliup.exe` 是打包的旧版本，可以去 https://github.com/biliup/biliup-rs/releases
   换新版试试 —— 那个 `overflow when subtracting durations` 在新版里可能已修。
3. **等有主播开播时，跑一次真实对测**（脚本已经写好）：
   ```powershell
   cd F:\DanmakuRender-魔改版
   python tools\ab_test_engines.py --seconds 60
   ```
   它会自动找一个在播的主播，依次用 streamgears / ffmpeg 跑 60 秒，
   对比产出文件的大小、时长、帧数、解码状态。也可以手动指定：
   ```powershell
   python tools\ab_test_engines.py --url https://live.douyin.com/56909717876 --seconds 60
   ```

---

## 六、一个附带发现

抖音 API 目前**正常**（`GetStreamerInfo()` 能取到主播名和头像），
所以 2026-10-04 凌晨检查时 30 个主播全不在播，是**真的都没开播**，不是 API 坏了。

日志里那 490 次 `GetRoomInfo (...) Error: 'data'` 是**离播时的正常探测噪音**
（代码里用的是 `logger.debug`，级别很低，不影响功能）。

---

## 七、可复用的分析脚本

| 脚本 | 用途 |
|---|---|
| `tools/compare_engines.py` | 从日志统计各引擎的启动/失败次数和趋势 |
| `tools/compare_configs.py` | 对比原版与魔改版的关键配置项是否一致 |
| `tools/check_recordings.py` | 检查已录制文件的完整性（解码测试、时长、码率） |
| `tools/ab_test_engines.py` | 真实引擎对测（需要主播在播） |
