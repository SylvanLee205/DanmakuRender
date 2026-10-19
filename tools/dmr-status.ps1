# DMR 状态面板
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'SilentlyContinue'
$root = 'F:\DanmakuRender_AutoUp'
$out  = Join-Path $root '直播回放'

function Line { param($c='DarkGray') Write-Host ('-' * 66) -ForegroundColor $c }

Write-Host ''
Write-Host '  DMR 状态面板' -ForegroundColor White
Write-Host ('  ' + (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) -ForegroundColor DarkGray
Line

# ---------- 1. 进程 ----------
$procs = @(Get-Process python -ErrorAction SilentlyContinue)
if ($procs.Count -gt 0) {
    $oldest = ($procs | Sort-Object StartTime | Select-Object -First 1).StartTime
    $up = (Get-Date) - $oldest
    Write-Host ('  [运行中]  ' + $procs.Count + ' 个进程   已运行 ' + $up.ToString('hh\:mm\:ss')) -ForegroundColor Green
} else {
    Write-Host '  [未运行]  没有 python 进程' -ForegroundColor Red
}

# ---------- 2. 正在录制 ----------
Write-Host ''
Write-Host '  正在录制' -ForegroundColor Cyan
# ⚠️ 不能看 LastWriteTime / Length：这台机器 F 盘的目录元数据有缓存，
#    实测正在写入的 234 MB 分段被读成 103.5 MB、时间戳停在 9 分钟前，
#    会误报"录制卡住"。必须开句柄取真实长度，并隔 2 秒再取一次比增量。
function Get-RealSize {
    param($Path)
    try {
        $fs = [System.IO.File]::Open($Path, 'Open', 'Read', 'ReadWrite')
        $len = $fs.Length
        $fs.Close()
        return $len
    } catch { return -1 }
}

$rec = @(Get-ChildItem $out -Recurse -File -ErrorAction SilentlyContinue |
         Where-Object { $_.Name -like '*正在录制*' -and $_.Extension -eq '.ts' })
if ($rec.Count -gt 0) {
    $before = @{}
    foreach ($f in $rec) { $before[$f.FullName] = Get-RealSize $f.FullName }
    Start-Sleep -Seconds 2
    foreach ($f in $rec) {
        $now = Get-RealSize $f.FullName
        $prev = $before[$f.FullName]
        $mb  = if ($now -ge 0) { [math]::Round($now / 1MB, 1) } else { 0 }
        $who = $f.Directory.Name
        if ($now -gt $prev) {
            $rate = [math]::Round(($now - $prev) / 2 / 1MB, 2)
            Write-Host ('    ' + $who.PadRight(16) + ('{0,8} MB' -f $mb) + ('   写入中 +' + $rate + ' MB/s')) -ForegroundColor Green
        } else {
            Write-Host ('    ' + $who.PadRight(16) + ('{0,8} MB' -f $mb) + '   !! 2 秒内没有增长，请复核') -ForegroundColor Yellow
        }
    }
} else {
    Write-Host '    (无活动录制)' -ForegroundColor DarkGray
}

# ---------- 3. 今日完成 ----------
Write-Host ''
Write-Host '  今日已保存' -ForegroundColor Cyan
$done = @(Get-ChildItem $out -Recurse -File -ErrorAction SilentlyContinue |
          Where-Object { $_.Extension -eq '.ts' -and $_.Name -notlike '*正在录制*' -and $_.LastWriteTime -gt (Get-Date).Date } |
          Sort-Object LastWriteTime -Descending | Select-Object -First 6)
if ($done.Count -gt 0) {
    foreach ($f in $done) {
        $mb = [math]::Round($f.Length / 1MB, 1)
        Write-Host ('    ' + $f.LastWriteTime.ToString('HH:mm') + '  ' + $f.Directory.Name.PadRight(16) + ('{0,9} MB' -f $mb)) -ForegroundColor Gray
    }
} else {
    Write-Host '    (今天还没有完成的回放)' -ForegroundColor DarkGray
}

# ---------- 4. 日志异常 ----------
Write-Host ''
Write-Host '  最近异常（当前日志）' -ForegroundColor Cyan
$log = Get-ChildItem (Join-Path $root 'logs') -Filter 'DMR-*.log' -ErrorAction SilentlyContinue |
       Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($log) {
    $bad = @(Get-Content $log.FullName -Tail 400 -Encoding UTF8 -ErrorAction SilentlyContinue |
             Where-Object { $_ -match '\[(error|critical|warning)\]' } | Select-Object -Last 5)
    if ($bad.Count -gt 0) {
        foreach ($b in $bad) {
            $s = if ($b.Length -gt 110) { $b.Substring(0, 110) } else { $b }
            Write-Host ('    ' + $s) -ForegroundColor Yellow
        }
    } else {
        Write-Host '    无 error / warning' -ForegroundColor Green
    }
} else {
    Write-Host '    (找不到日志)' -ForegroundColor DarkGray
}

# ---------- 5. 磁盘 ----------
Write-Host ''
Write-Host '  磁盘' -ForegroundColor Cyan
Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -in @('C','D','E','F') } |
  ForEach-Object {
      $usedPct = if ($_.Used + $_.Free -gt 0) { [math]::Round($_.Used / ($_.Used + $_.Free) * 100, 0) } else { 0 }
      $freeGB  = [math]::Round($_.Free / 1GB, 1)
      $color = if ($freeGB -lt 50) { 'Red' } elseif ($freeGB -lt 200) { 'Yellow' } else { 'Gray' }
      Write-Host ('    ' + $_.Name + ':  剩余 ' + $freeGB + ' GB  (' + $usedPct + '% 已用)') -ForegroundColor $color
  }

Line
Write-Host ''
