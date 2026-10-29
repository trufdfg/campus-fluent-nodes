r"""校园网计算从机小工具：按计算机名找三台从机，检查连通、远程执行 PowerShell、传文件、后台跑 Fluent（或任意命令行）、查看和停止任务。

只用 Python 标准库（3.8+），靠系统自带的 ssh / scp。
用之前（部署，详见 SKILL.md）：
  1. 私钥放到 ~/.ssh/wb_nodes（找 sjh 私下要，不要放进任何仓库）
  2. python node.py refresh            按计算机名找到从机 IP，写进 ~/.ssh/config
  3. python node.py check              逐台检查能不能接通
  4. python node.py roots              看每台建议的文件保存地址；确认后
     python node.py roots --set <从机> "<路径>"   三台都确认之前，派任务的命令会拒绝执行

任务文件放在各从机的保存地址下，按"项目\任务"分类：
  <保存地址>\<项目>\<任务>\model\     输入：.cas.h5、.dat.h5、.jou
                          results\   输出：journal 里写出的文件
                          logs\      run.log（Fluent 的屏幕输出）、job.json
命令里的 JOB 写成 "项目/任务"（只写任务名时归到"未分类"）。fluent 和 run 的工作目录都是任务目录，
journal 里用 model/a.cas.h5、results/b.dat.h5 这样的相对路径。

用法：
  python node.py refresh                          按计算机名重新解析 IP，写回 ~/.ssh/config（之后可直接 ssh n5950x）
  python node.py check                            部署检查：私钥、ssh、各从机端口和登录
  python node.py roots [--set 从机 路径]           查看 / 设置每台从机的文件保存地址
  python node.py info                             各从机 CPU 占用、内存、磁盘、在跑的 Fluent / COMSOL
  python node.py ps n5950x "Get-Date"             远程执行 PowerShell（UTF-8 输出，不怕中文和引号）
  python node.py push n5950x a.cas.h5 项目/任务 [--sub model]   上传到任务的 model\（或指定子目录）
  python node.py pull n5950x 项目/任务 b.dat.h5 .  下载；只写文件名时取 results\ 下的，也可写 logs/run.log 等
  python node.py fluent n5950x 项目/任务 run.jou [--np N] [--dim 3ddp] [--prio idle|below|normal|above|high]
                                                  后台跑 Fluent：fluent 3ddp -g -tN -i model\run.jou（断网、关 SSH 都不影响）
  python node.py run n5950x 项目/任务 "model\my.bat" [--prio ...]
                                                  后台跑任意命令行（经 cmd.exe，工作目录是任务目录，输出写 logs\run.log）
  python node.py status n5950x [项目/任务]        是否在跑 + run.log 末尾（不写任务就列出全部任务）
  python node.py stop n5950x 项目/任务            结束该任务的全部进程
"""
import argparse
import base64
import getpass
import ipaddress
import json
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

KEY = Path.home() / ".ssh" / "wb_nodes"
SSH_CONFIG = Path.home() / ".ssh" / "config"
CONFIG = Path.home() / ".campus_nodes.json"   # 本机设置：各从机的文件保存地址
LAN = ipaddress.ip_network("172.24.80.0/20")   # 从机所在的校园网 Wi-Fi 网段
PRIORITY = {"idle": 64, "below": 16384, "normal": 32, "above": 32768, "high": 128}   # Win32 PriorityClass
SUBDIRS = ("model", "results", "logs")
DEFAULT_PROJECT = "未分类"

NODES = {
    # 有别人的程序时会占掉一部分 CPU，派任务前先 info 看占用
    "n5950x": dict(host="DESKTOP-1E0VORE", user="Admin", cores=16, prio="normal", suggest=r"C:\Users\Admin\Desktop\WB",
                   version="2024 R1", fluent=r"C:\ANSYS\2024 R1\v241\fluent\ntbin\win64\fluent.exe", ip="172.24.95.50"),
    # 里面那台。有别人的 DMol3 以 Idle 优先级占满 24 核。约定：只用 idle 优先级，和它平分，不要用 below/normal 去抢
    "limian": dict(host="DESKTOP-POHVFB3", user="Administrator", cores=24, prio="idle", suggest=r"E:\WB",
                   version="2024 R1", fluent=r"D:\ANSYS2024\ANSYS Inc\v241\fluent\ntbin\win64\fluent.exe", ip="172.24.88.190"),
    # 门口那台。也有别人的 DMol3（Idle 优先级），这台约定用 normal。Fluent 是 2022 R1，打不开 2024 R1 存的 case
    "menkou": dict(host="DESKTOP-2HU6S6M", user="Administrator", cores=24, prio="normal", suggest=r"E:\WB",
                   version="2022 R1", fluent=r"D:\Program Files\ANSYS Inc\v221\fluent\ntbin\win64\fluent.exe", ip="172.24.94.237"),
}
# ip 是 2026-10-29 的地址，只在按计算机名解析不到、~/.ssh/config 里也没有时兜底用

# 读日志末尾：共享读（Fluent 正在写也能读），先按 UTF-8 解码，不行再按系统编码（GBK）
PS_TAIL = """
function Tail($f, $n = 8) {
    $fs = [IO.File]::Open($f, 'Open', 'Read', 'ReadWrite')
    try {
        $len = [Math]::Min(8192, $fs.Length); [void]$fs.Seek(-$len, 'End')
        $b = New-Object byte[] $len; [void]$fs.Read($b, 0, $len); $cut = $len -lt $fs.Length
    } finally { $fs.Close() }
    $i = 0; while ($i -lt $b.Length -and ($b[$i] -band 0xC0) -eq 0x80) { $i++ }
    try { $t = (New-Object Text.UTF8Encoding($false, $true)).GetString($b, $i, $b.Length - $i) }
    catch { $t = [Text.Encoding]::Default.GetString($b) }
    $lines = @($t -split "`r?`n" | Where-Object { $_.Trim() -ne '' })
    if ($cut -and $lines.Count -gt 1) { $lines = $lines[1..($lines.Count - 1)] }
    $lines | Select-Object -Last $n | ForEach-Object { "   $_" }
}
"""


def _cfg():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def root(node):
    """这台从机上确认过的文件保存地址；没确认就停下，提示先跑 roots。"""
    r = _cfg().get("roots", {}).get(node)
    if not r:
        sys.exit(f"{node} 的文件保存地址还没确认：先运行 python node.py roots 查看建议，"
                 f"再运行 python node.py roots --set {node} \"<路径>\"")
    return r


def resolve(host):
    """计算机名 -> 校园网段内、22 端口能连上的 IPv4；找不到返回 None。"""
    try:
        infos = socket.getaddrinfo(host, 22, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror:
        return None
    ips = [i[4][0] for i in infos if ipaddress.ip_address(i[4][0]) in LAN]
    for ip in dict.fromkeys(ips):
        try:
            with socket.create_connection((ip, 22), timeout=2):
                return ip
        except OSError:
            pass
    return ips[0] if ips else None


def _config_ips():
    old = SSH_CONFIG.read_text(encoding="utf-8") if SSH_CONFIG.exists() else ""
    return dict(re.findall(r"^Host (\S+)\n\s+HostName (\S+)", old, re.M))


def refresh():
    """重新解析各从机 IP，把 ~/.ssh/config 里两行标记之间的部分整段重写。
    名字解析不到时沿用 config 里上次的 IP，再没有就用 NODES 里写的兜底 ip。"""
    SSH_CONFIG.parent.mkdir(exist_ok=True)
    old = SSH_CONFIG.read_text(encoding="utf-8") if SSH_CONFIG.exists() else ""
    prev = _config_ips()
    blocks = ["# >>> campus nodes（由 node.py refresh 生成，勿手改）"]
    for alias, n in NODES.items():
        ip = resolve(n["host"]) or prev.get(alias) or n.get("ip")
        print(f"{alias:7s} {n['host']:16s} -> {ip}")
        blocks.append(f"Host {alias}\n    HostName {ip}\n    HostKeyAlias {n['host']}\n    User {n['user']}")
    blocks.append(f"Host {' '.join(NODES)}\n    IdentityFile ~/.ssh/wb_nodes\n    IdentitiesOnly yes\n"
                  "    StrictHostKeyChecking accept-new\n    ConnectTimeout 10\n"
                  "    ServerAliveInterval 30\n    LogLevel ERROR")
    blocks.append("# <<< campus nodes")
    rest = re.sub(r"# >>> campus nodes.*?# <<< campus nodes\n?", "", old, flags=re.S).strip()
    SSH_CONFIG.write_text("\n".join(blocks) + "\n" + (rest + "\n" if rest else ""), encoding="utf-8")


def check():
    """部署检查：私钥、ssh 命令、~/.ssh/config，以及每台从机的 22 端口和密钥登录。全部接通返回 True。"""
    good = True
    if KEY.exists():
        print(f"✓ 私钥 {KEY}")
    else:
        print(f"✗ 没有私钥 {KEY}：找 sjh 要 wb_nodes 文件，放到这个位置")
        good = False
    if not shutil.which("ssh"):
        print("✗ 找不到 ssh 命令：Windows 设置 > 系统 > 可选功能 里装上 OpenSSH 客户端")
        return False
    ips = _config_ips()
    if not all(a in ips for a in NODES):
        print("✗ ~/.ssh/config 里还没有从机：先运行 python node.py refresh")
        return False
    for alias, n in NODES.items():
        ip = ips[alias]
        try:
            socket.create_connection((ip, 22), timeout=3).close()
        except OSError:
            print(f"✗ {alias}：{ip} 的 22 端口连不上。确认本机连着校园网；从机可能关机或换了 IP，"
                  f"先再跑一次 refresh，还不行找 sjh")
            good = False
            continue
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", alias, "hostname"], capture_output=True)
        out = r.stdout.decode("utf-8", "replace").strip()
        err = r.stderr.decode("utf-8", "replace").strip()
        if r.returncode == 0 and out.lower() == n["host"].lower():
            print(f"✓ {alias}：已接通（{n['host']}，{ip}）")
            continue
        good = False
        if "UNPROTECTED PRIVATE KEY" in err or "bad permissions" in err.lower():
            print(f"✗ {alias}：私钥文件权限太宽，执行下面这行后再试：\n"
                  f"    icacls \"{KEY}\" /inheritance:r /grant:r \"{getpass.getuser()}:F\"")
        elif "Permission denied" in err:
            print(f"✗ {alias}：从机拒绝了这把私钥（文件不对，或从机上还没登记），找 sjh")
        elif r.returncode == 0:
            print(f"✗ {alias}：登录到了 {out}，不是 {n['host']}，IP 可能被别的机器占了，先跑 refresh")
        else:
            print(f"✗ {alias}：登录失败：{err or out}")
    print("全部接通" if good else "还有没接通的，按上面的提示处理")
    return good


def ps(node, script, check=True):
    """在从机上执行一段 PowerShell，返回 UTF-8 文本输出。"""
    script = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ProgressPreference = 'SilentlyContinue'\n"
              + script)
    b64 = base64.b64encode(script.encode("utf-16-le")).decode()
    r = subprocess.run(["ssh", node, f"powershell -NoProfile -NonInteractive -EncodedCommand {b64}"],
                       capture_output=True)
    out = r.stdout.decode("utf-8", "replace")
    err = r.stderr.decode("utf-8", "replace").strip()
    if check and r.returncode != 0:
        raise RuntimeError(f"{node} 远程命令失败（{r.returncode}）：{err or out}")
    return out + (("\n" + err) if err else "")


def _q(v):
    """PowerShell 单引号字符串转义。"""
    return str(v).replace("'", "''")


def roots(node=None, path=None):
    """不带参数：列出每台的保存地址（已确认的或建议的）、是否已存在、所在盘剩余空间、里面有多少项。
    带 --set：把这台的保存地址记进 ~/.campus_nodes.json。"""
    cfg = _cfg()
    have = cfg.setdefault("roots", {})
    if node:
        p = path.replace("/", "\\").rstrip("\\")
        if not re.match(r"^[A-Za-z]:\\.+", p):
            sys.exit(f"路径要写成从机上的完整路径，例如 {NODES[node]['suggest']}，不能只写盘符")
        if p.split("\\")[-1].lower() == "sjh":
            sys.exit("sjh 文件夹是 sjh 自己的，换一个")
        have[node] = p
        CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{node} 的文件保存地址设为 {p}")
        return
    for alias, n in NODES.items():
        p = have.get(alias)
        label = f"已确认 {p}" if p else f"未确认，建议 {n['suggest']}"
        p = p or n["suggest"]
        try:
            out = ps(alias, f"""
$p = '{_q(p)}'
$d = Get-PSDrive -Name $p.Substring(0, 1) -ErrorAction SilentlyContinue
$free = if ($d) {{ "{{0:N0}} GB" -f ($d.Free / 1GB) }} else {{ "没有这个盘" }}
if (Test-Path $p) {{ "已存在，里面有 $(@(Get-ChildItem $p -Force -ErrorAction SilentlyContinue).Count) 项；所在盘剩余 $free" }}
else {{ "还不存在（第一次派任务时会自动建）；所在盘剩余 $free" }}
""").strip()
        except Exception as e:
            out = f"连不上（{e}）"
        print(f"== {alias}（{n['host']}）  {label}\n   {out}")


def jobdir(node, job):
    """"项目/任务" -> 从机上的任务目录；只写任务名归到"未分类"。"""
    parts = [p for p in re.split(r"[\\/]", job) if p]
    if len(parts) == 1:
        parts.insert(0, DEFAULT_PROJECT)
    return root(node) + "\\" + "\\".join(parts)


def _mkjob(node, job):
    d = jobdir(node, job)
    ps(node, f"$d = '{_q(d)}'; foreach ($s in {', '.join(repr(s) for s in SUBDIRS)}) "
             f"{{ New-Item -ItemType Directory -Force \"$d\\$s\" | Out-Null }}")
    return d


def push(node, local, job, sub="model"):
    d = _mkjob(node, job)
    subprocess.run(["scp", "-q", str(local), f"{node}:{(d + chr(92) + sub).replace(chr(92), '/')}/"], check=True)


def pull(node, job, name, local):
    """name 只写文件名时取 results\\ 下的；也可写 "logs/run.log" 这样的相对路径。"""
    if not re.search(r"[\\/]", name):
        name = "results/" + name
    src = (jobdir(node, job) + "\\" + name).replace("\\", "/")
    subprocess.run(["scp", "-q", f"{node}:{src}", str(local)], check=True)


def _launch(node, job, cmdline, prio, **meta):
    """用 WMI 建进程：不属于 SSH 会话，断网或会话结束都不会被杀。工作目录是任务目录，PID 等写进 logs\\job.json。
    同一个任务还在跑时拒绝再启动（job.json 只记最后一次的 PID，重复启动后第一次的就管不到了）。"""
    d = _mkjob(node, job)
    prio = prio or NODES[node]["prio"]
    fields = "".join(f"; {k} = '{_q(v)}'" for k, v in meta.items())
    out = ps(node, f"""
$d = '{_q(d)}'
if (Test-Path "$d\\logs\\job.json") {{
    $old = Get-Content "$d\\logs\\job.json" -Raw | ConvertFrom-Json
    if (Get-Process -Id $old.pid -ErrorAction SilentlyContinue) {{ throw "这个任务还在跑（PID=$($old.pid)），先 stop，或者换个任务名" }}
}}
$si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{{PriorityClass = [uint32]{PRIORITY[prio]}}}
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{{
    CommandLine = '{_q(cmdline)}'; CurrentDirectory = $d; ProcessStartupInformation = $si }}
if ($r.ReturnValue -ne 0) {{ throw "Win32_Process.Create 返回 $($r.ReturnValue)" }}
@{{ pid = $r.ProcessId; prio = '{prio}'; started = (Get-Date -Format s); cmd = '{_q(cmdline)}'{fields} }} |
    ConvertTo-Json | Set-Content -Encoding UTF8 "$d\\logs\\job.json"
"已启动 PID=$($r.ProcessId)  目录 $d"
""")
    print(out.strip())


def run(node, job, command, prio=None, np=""):
    """后台跑任意命令行（如自己写的 .bat，放在 model\\ 里）。WMI 不能直接启动 .bat，
    所以经 cmd.exe /s /c；工作目录是任务目录，标准输出和错误写进 logs\\run.log。"""
    _launch(node, job, f'cmd.exe /s /c "{command} > logs\\run.log 2>&1"', prio, np=np)


def fluent(node, job, journal, np=None, dim="3ddp", prio=None):
    """后台跑 Fluent：fluent <dim> -g -t<np> -i model\\<journal> -wait，屏幕输出写 logs\\run.log。
    -wait 让启动器等 Fluent 算完才退出，status 才能看出是否还在跑。np 默认用满这台的物理核。"""
    n = NODES[node]
    np = np or n["cores"]
    run(node, job, f'"{n["fluent"]}" {dim} -g -t{np} -i "model\\{journal}" -wait', prio, np=np)


def _jobs_ps(node, job):
    """PowerShell 表达式：要查看的任务目录列表（不写任务时列出保存地址下的全部任务）。"""
    if job:
        return f"@('{_q(jobdir(node, job))}')"
    return f"""@(Get-ChildItem '{_q(root(node))}' -Recurse -Depth 3 -Filter job.json -ErrorAction SilentlyContinue |
    Where-Object {{ $_.Directory.Name -eq 'logs' }} | ForEach-Object {{ $_.Directory.Parent.FullName }})"""


def status(node, job=None):
    print(ps(node, PS_TAIL + f"""
foreach ($d in {_jobs_ps(node, job)}) {{
    $jf = "$d\\logs\\job.json"
    if (-not (Test-Path $jf)) {{ "== $d  没有 job.json"; continue }}
    $j = Get-Content $jf -Raw | ConvertFrom-Json
    $p = Get-Process -Id $j.pid -ErrorAction SilentlyContinue
    $state = if ($p) {{ "运行中" }} else {{ "已结束" }}
    "== $d  $state  PID=$($j.pid)  启动于 $($j.started)  核数=$($j.np)  优先级=$($j.prio)"
    if (Test-Path "$d\\logs\\run.log") {{ Tail "$d\\logs\\run.log" }}
}}
""").rstrip())


def stop(node, job):
    """结束一个任务。Fluent 的 mpiexec、MPI 代理和计算进程（fl_mpi*）脱离了从 cmd.exe 往下的进程树，要另外找：
    1. 记下进程树（只认任务启动之后建的进程，防 PID 复用）；
    2. 树里的 Fluent 主进程在监听一个端口，计算进程和 mpiexec 的命令行里带着它（-mport ...:端口:），按端口找回来；
    3. 跑这次任务生成的 cleanup-fluent-*.bat（Fluent 自己写的，按 PID 杀计算进程、host 和 cortex）；
    4. 上面找到的进程还活着的（许可客户端 ansyscl 等）全部结束。
    刚启动、还没写出 cleanup 脚本时 stop 也靠第 2 步清干净。"""
    print(ps(node, f"""
$d = '{_q(jobdir(node, job))}'
$j = Get-Content "$d\\logs\\job.json" -Raw | ConvertFrom-Json
$t0 = ([datetime]$j.started).AddSeconds(-5)   # started 是 Create 返回后才记的，留点余量
$all = @(Get-CimInstance Win32_Process)
$tree = @([int]$j.pid); $i = 0
while ($i -lt $tree.Count) {{
    $tree += @($all | Where-Object {{ $_.ParentProcessId -eq $tree[$i] -and $_.CreationDate -ge $t0 }} | ForEach-Object ProcessId)
    $i++
}}
$ports = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object {{ $tree -contains $_.OwningProcess }} | ForEach-Object LocalPort | Sort-Object -Unique)
$mpi = @($all | Where-Object {{ $_.Name -match '^(fl_mpi|mpiexec|hydra)' -and $_.CreationDate -ge $t0 -and $_.CommandLine }} |
    Where-Object {{ $c = $_.CommandLine; @($ports | Where-Object {{ $c -match ":$_`:" }}).Count }})
$tree += @($mpi | ForEach-Object ProcessId) + @($mpi | Where-Object Name -like 'fl_mpi*' | ForEach-Object ParentProcessId)
Get-ChildItem $d -Filter 'cleanup-fluent-*.bat' -ErrorAction SilentlyContinue |
    Where-Object {{ $_.LastWriteTime -ge $t0 }} |
    ForEach-Object {{ "运行 $($_.Name)"; cmd.exe /c "`"$($_.FullName)`"" 2>&1 | Out-Null }}
$left = @($tree | Where-Object {{ Get-Process -Id $_ -ErrorAction SilentlyContinue }})
$left | ForEach-Object {{ Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }}
"已结束 $d（cleanup 之后又结束了 $($left.Count) 个剩余进程）"
""").strip())


def info():
    have = _cfg().get("roots", {})
    for alias, n in NODES.items():
        where = have.get(alias) or "未确认（先跑 roots）"
        try:
            out = ps(alias, """
$cpu = Get-CimInstance Win32_Processor
$os = Get-CimInstance Win32_OperatingSystem
"{0}  占用 {1}%" -f $cpu.Name.Trim(), $cpu.LoadPercentage
"内存 空闲 {0:N1} / {1:N1} GB" -f ($os.FreePhysicalMemory / 1MB), ($os.TotalVisibleMemorySize / 1MB)
Get-PSDrive -PSProvider FileSystem | Where-Object Used -ne $null |
    ForEach-Object { "磁盘 {0}: 剩余 {1:N1} GB" -f $_.Name, ($_.Free / 1GB) }
$f = @(Get-Process fl_mpi* -ErrorAction SilentlyContinue)
$c = @(Get-Process comsol* -ErrorAction SilentlyContinue)
"在跑的 Fluent 计算进程 {0} 个，COMSOL 进程 {1} 个" -f $f.Count, $c.Count
""")
            print(f"== {alias} ({n['host']})  Fluent {n['version']}  文件放在 {where}\n"
                  + "\n".join("   " + l for l in out.strip().splitlines()))
        except Exception as e:
            print(f"== {alias}: 连不上（{e}）")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("refresh")
    sub.add_parser("check")
    a = sub.add_parser("roots"); a.add_argument("--set", nargs=2, metavar=("NODE", "PATH"))
    sub.add_parser("info")
    a = sub.add_parser("ps"); a.add_argument("node", choices=NODES); a.add_argument("script")
    a = sub.add_parser("push"); a.add_argument("node", choices=NODES); a.add_argument("local"); a.add_argument("job")
    a.add_argument("--sub", default="model", choices=SUBDIRS)
    a = sub.add_parser("pull"); a.add_argument("node", choices=NODES); a.add_argument("job"); a.add_argument("name")
    a.add_argument("local")
    a = sub.add_parser("fluent"); a.add_argument("node", choices=NODES); a.add_argument("job"); a.add_argument("journal")
    a.add_argument("--np", type=int); a.add_argument("--dim", default="3ddp", choices=["2d", "2ddp", "3d", "3ddp"])
    a.add_argument("--prio", choices=list(PRIORITY))
    a = sub.add_parser("run"); a.add_argument("node", choices=NODES); a.add_argument("job"); a.add_argument("command")
    a.add_argument("--prio", choices=list(PRIORITY))
    a = sub.add_parser("status"); a.add_argument("node", choices=NODES); a.add_argument("job", nargs="?")
    a = sub.add_parser("stop"); a.add_argument("node", choices=NODES); a.add_argument("job")
    a = p.parse_args()
    if a.cmd == "refresh": refresh()
    elif a.cmd == "check": sys.exit(0 if check() else 1)
    elif a.cmd == "roots":
        if a.set and a.set[0] not in NODES:
            sys.exit(f"没有从机 {a.set[0]}，只有 {', '.join(NODES)}")
        roots(*(a.set or ()))
    elif a.cmd == "info": info()
    elif a.cmd == "ps": print(ps(a.node, a.script, check=False))
    elif a.cmd == "push": push(a.node, a.local, a.job, a.sub)
    elif a.cmd == "pull": pull(a.node, a.job, a.name, a.local)
    elif a.cmd == "fluent": fluent(a.node, a.job, a.journal, a.np, a.dim, a.prio)
    elif a.cmd == "run": run(a.node, a.job, a.command, a.prio)
    elif a.cmd == "status": status(a.node, a.job)
    elif a.cmd == "stop": stop(a.node, a.job)
