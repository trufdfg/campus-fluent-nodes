# 使用细节

## 命令一览

| 命令 | 作用 |
|---|---|
| `node.py refresh` | 按计算机名找三台从机的 IP，写进 `~/.ssh/config`。从机重启后 IP 会变，连不上时先跑它 |
| `node.py check` | 部署检查：私钥、ssh 命令，以及每台的 22 端口和密钥登录，逐台给出结论 |
| `node.py roots [--set 从机 路径]` | 查看 / 设置每台的文件保存地址（存在 `%USERPROFILE%\.campus_nodes.json`） |
| `node.py info` | 三台的 CPU 占用、内存、磁盘，以及在跑的 Fluent / COMSOL 进程数 |
| `node.py push 从机 本地文件 项目/任务 [--sub model]` | 上传到任务的 `model\`（或 `results\`、`logs\`） |
| `node.py pull 从机 项目/任务 文件名 本地目录` | 下载。只写文件名时取 `results\` 下的，也可写 `logs/run.log` |
| `node.py fluent 从机 项目/任务 journal [--np N] [--dim 3ddp] [--prio ...]` | 后台跑 Fluent，屏幕输出写进 `logs\run.log` |
| `node.py run 从机 项目/任务 "命令行" [--prio ...]` | 后台跑任意命令行（经 `cmd.exe`），输出写进 `logs\run.log` |
| `node.py status 从机 [项目/任务]` | 是否在跑、启动时间、核数、`run.log` 最后几行。不写任务就列出这台上你的全部任务 |
| `node.py stop 从机 项目/任务` | 结束这个任务的全部进程 |
| `node.py ps 从机 "PowerShell 脚本"` | 在从机上执行一段 PowerShell |

## 任务是怎么跑的

- `fluent` 和 `run` 都通过 WMI 在从机上建进程，进程不属于 SSH 会话，所以断网、关掉自己电脑上的窗口都不影响计算。PID、启动时间、核数、优先级记在 `logs\job.json`。
- `fluent` 实际执行 `fluent <dim> -g -t<核数> -i model\<journal> -wait`。`-wait` 让启动器等 Fluent 算完才退出，`status` 才能看出是否还在跑。
- 同一个任务还在跑时，`fluent` / `run` 会拒绝再启动：`job.json` 只记最后一次的 PID，重复启动后第一次的进程就管不到了。
- Fluent 的计算进程（`fl_mpi*`）挂在一个脱离进程树的 MPI 代理下面，直接杀进程树杀不干净。`stop` 会先按 Fluent 主进程监听的端口把它们找回来，再运行 Fluent 自己生成的 `cleanup-fluent-*.bat`，最后结束剩下的进程。刚启动几秒、正在计算时 stop 都实测过能清干净。
- WMI 不能直接启动 `.bat`（能拿到 PID，但批处理根本不执行），所以 `.bat` 一律用 `run`。

## 结果怎么拿回来

从机连的都是校园网 Wi-Fi，往回传只有约 3 MB/s：一个 280 MB 的 `.dat.h5` 要一分半左右，几个 GB 要半小时以上，`scp` 断了不能续传。

- 只拉需要的文件，比如最后一步的 `.cas.h5` / `.dat.h5`，或 journal 里导出的数据。
- 大文件挑晚上拉。
- 只想看看结果的话，远程桌面到从机上直接打开，不用传文件。

## 注意事项

- **从机重启后 IP 会变**：先跑 `refresh`，再 `check`。
- **从机重启会杀掉正在算的任务**：Windows 更新可能自动重启从机。长任务开自动保存，开跑前跟 sjh 打个招呼。
- **`ps` 的脚本不能太长**：从机上是 Windows PowerShell 5.1，脚本超过约 3000 字符时命令行会被截断，报"字符串缺少终止符"之类的错。
- **版本**：`menkou` 的 Fluent 是 2022 R1，打不开 2024 R1 存的 case。
- **内存**：两台 285K 上别人的 DMol3 占了不少内存，2026-11-01 空闲 `limian` 约 27 GB、`menkou` 约 12 GB，大网格先 `info` 看一下。
- **路径**：项目名和任务名用英文或拼音，Fluent 碰到中文路径容易出问题。

## 从机上的 Fluent

| 从机 | 计算机名 | 登录用户 | fluent.exe |
|---|---|---|---|
| `n5950x` | DESKTOP-1E0VORE | Admin | `C:\ANSYS\2024 R1\v241\fluent\ntbin\win64\fluent.exe` |
| `limian` | DESKTOP-POHVFB3 | Administrator | `D:\ANSYS2024\ANSYS Inc\v241\fluent\ntbin\win64\fluent.exe` |
| `menkou` | DESKTOP-2HU6S6M | Administrator | `D:\Program Files\ANSYS Inc\v221\fluent\ntbin\win64\fluent.exe` |

三台的 Fluent 许可都在各自机器上，不用另外配置。2026-10-29 三台都用 `-t16` 实测启动成功。
