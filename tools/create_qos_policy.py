"""正确地创建并持久化 QoS 限速策略（用已验证可靠的方式）。"""
import subprocess
import time

POLICY = 'DMR-CloudDrive-UploadLimit'
APP = r'C:\Program Files\CloudDrive\CloudDrive.exe'
PARAM = 33554432          # → 注册表 4194304 字节/秒 = 4 MB/s


def ps(cmd):
    r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return (r.stdout or '') + (r.stderr or '')


def show():
    out = ps(f"Get-NetQosPolicy -Name '{POLICY}' -ErrorAction SilentlyContinue | "
             "Select-Object Name,AppPathNameMatchCondition,"
             "ThrottleRateActionBitsPerSecond | Format-List | Out-String")
    print(out.strip() or '  （策略不存在）')
    reg = f"HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows\\QoS\\{POLICY}"
    out2 = ps(f"if (Test-Path '{reg}') {{ "
              f"$p = Get-ItemProperty '{reg}'; "
              f"Write-Output ('AppName=' + $p.AppName); "
              f"Write-Output ('ThrottleRate=' + $p.ThrottleRate) }} else {{ 'REG_NOT_FOUND' }}")
    print('  注册表:')
    for l in out2.strip().split('\n'):
        if l.strip():
            print(f'    {l.strip()}')


print('=' * 78)
print('1. 清理旧策略')
print('=' * 78)
ps(f"Remove-NetQosPolicy -Name '{POLICY}' -Confirm:$false -ErrorAction SilentlyContinue")
time.sleep(2)

print()
print('=' * 78)
print(f'2. 创建策略（参数 {PARAM} → 应为 4194304 字节/秒 = 4 MB/s）')
print('=' * 78)
out = ps(f"try {{ New-NetQosPolicy -Name '{POLICY}' "
         f"-AppPathNameMatchCondition '{APP}' "
         f"-ThrottleRateActionBitsPerSecond {PARAM} -ErrorAction Stop | Out-Null; 'OK' }} "
         f"catch {{ 'ERR: ' + $_.Exception.Message }}")
print(f'  {out.strip()[:200]}')
time.sleep(2)

print()
print('=' * 78)
print('3. 验证')
print('=' * 78)
show()

print()
print('=' * 78)
print('4. 重启 CD2')
print('=' * 78)
ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue")
time.sleep(8)
subprocess.Popen([APP, '--autostart'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(25)
out = ps("Get-Process CloudDrive -ErrorAction SilentlyContinue | "
         "ForEach-Object { $_.Id.ToString() + ' 启动于 ' + $_.StartTime.ToString('HH:mm:ss') }")
print('  ' + (out.strip() or '未启动'))
