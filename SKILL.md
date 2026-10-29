---
name: campus-fluent-nodes
description: 通过 SSH 使用校园网内的三台计算从机（n5950x、limian、menkou）跑 Fluent，包括首次部署（放私钥、检查连通、确认每台的文件保存地址）、传文件、后台开算、查看和停止任务、取回结果。用户提到这三台从机、"部署从机"、在从机上跑 Fluent 或往从机派任务时使用。
---

# 校园网计算从机（Fluent）

工具是本 skill 目录下的 `scripts/node.py`，只用 Python 标准库（3.8+），通过系统自带的 `ssh` / `scp` 连接从机。下文的 `node.py` 都指它，调用时写完整路径，例如 `python "<本 skill 目录>\scripts\node.py" check`。如果 `python` 命令不可用，改用 `py -3`。

三台从机都是 Windows，在校园网 Wi-Fi 上（172.24.x.x），归 sjh 管：

| 别名 | 配置 | Fluent | 默认优先级 | 情况 |
|---|---|---|---|---|
| `n5950x` | Ryzen 9 5950X 16 核，64 GB | 2024 R1 | normal | 有时有别人的程序占一部分 CPU |
| `limian` | Ultra 9 285K 24 核，96 GB | 2024 R1 | **idle** | 别人的 DMol3 以 idle 优先级占满 24 核 |
| `menkou` | Ultra 9 285K 24 核，96 GB | **2022 R1** | normal | 别人的 DMol3 以 idle 优先级占满 24 核 |

## 第一次使用：部署

按顺序做，每一步确认结果再做下一步。目标是让三台都能接通，并且每台的文件保存地址都由用户确认过。

1. **检查环境。** 运行 `python --version`（要 3.8 或更高）和 `ssh -V`（要能显示版本号）。没有 ssh 的话，让用户在"设置 > 系统 > 可选功能"里装上"OpenSSH 客户端"。
2. **放好私钥。** 确认 `%USERPROFILE%\.ssh\wb_nodes` 存在。不存在就请用户把 sjh 私下发的 `wb_nodes` 文件（没有扩展名）放进去：
   ```powershell
   New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
   Copy-Item "<用户存放 wb_nodes 的位置>\wb_nodes" "$env:USERPROFILE\.ssh\wb_nodes"
   ```
   **不要读取、打印或复制私钥的内容，也不要把它放进任何仓库或公开的地方。**
3. **生成连接配置：** `python node.py refresh`。它按计算机名找到三台的 IP，写进 `~/.ssh/config` 里 `# >>> campus nodes` 到 `# <<< campus nodes` 之间的部分，不动其他内容。
4. **检查连通：** `python node.py check`。三台都显示"✓ 已接通"才算通。没通就按它给的提示处理：
   - 私钥权限太宽：运行它给出的那行 `icacls` 命令，再 `check`。
   - 22 端口连不上：确认用户的电脑连着校园网（`ipconfig` 里有 172.24.x.x 的地址），再跑一次 `refresh` 和 `check`。还不行就是从机关机或换了 IP，请用户联系 sjh。
   - 从机拒绝了私钥：私钥文件不对，请用户联系 sjh。
5. **确认每台的文件保存地址。** 运行 `python node.py roots`，它会列出每台建议的文件夹、是否已经存在、里面有多少项、所在盘还剩多少空间。**逐台问用户**（有提问工具就用提问工具，每台一个问题）：用建议的地址，还是换一个。问的时候把 `roots` 列出的情况一起告诉用户。用户确认后逐台写入：
   ```powershell
   python node.py roots --set n5950x "C:\Users\Admin\Desktop\WB"
   python node.py roots --set limian "E:\WB"
   python node.py roots --set menkou "E:\WB"
   ```
   引号里换成用户确认的路径。设置保存在 `%USERPROFILE%\.campus_nodes.json`。三台都设好之前，`push`、`fluent`、`status` 等命令会拒绝执行。不能选 sjh 文件夹，也不要选别人的文件夹。
6. **收尾：** 运行 `python node.py info`，把三台的 CPU、内存、磁盘情况告诉用户，部署完成。

## 日常用法

```powershell
python node.py info                                          # 三台忙不忙、内存和磁盘
python node.py push n5950x D:\cases\a.cas.h5 xielou/case15   # 上传到任务的 model\
python node.py push n5950x D:\cases\a.dat.h5 xielou/case15
python node.py push n5950x D:\cases\run.jou xielou/case15
python node.py fluent n5950x xielou/case15 run.jou --np 8    # 后台开算
python node.py status n5950x xielou/case15                   # 是否在跑 + run.log 最后几行
python node.py pull n5950x xielou/case15 done.dat.h5 D:\results\   # 取回 results\ 下的文件
python node.py stop n5950x xielou/case15                     # 中途停掉
```

- 任务写成 `项目/任务`，会放在这台保存地址下的 `项目\任务\`，里面有 `model\`（输入）、`results\`（输出）、`logs\`（`run.log` 是 Fluent 的全部屏幕输出）。项目名和任务名用英文或拼音。
- `fluent` 实际执行的是 `fluent 3ddp -g -t<核数> -i model\<journal> -wait`。`--np` 不写就用满这台的核数，`--dim` 可选 `2d`、`2ddp`、`3d`、`3ddp`。任务进程不属于 SSH 会话，断网也不影响计算。
- 同一个任务还在跑时不能再启动，要先 `stop` 或换个任务名。
- 其他命令：`run`（后台跑任意命令行，`.bat` 一定要用它），`ps`（在从机上执行一段 PowerShell）。

## 写 journal

工作目录是任务目录，路径用相对路径。下面这个例子在 n5950x 上用真实算例跑通过：

```
/file/confirm-overwrite? no
/file/read-case-data "model/a.cas.h5"
/file/auto-save/data-frequency 60
/file/auto-save/root-name "results/auto"
/solve/dual-time-iterate 240 20
/file/write-case-data "results/done.cas.h5"
/exit yes
```

- 第 1 行必须有：不关覆盖确认的话，碰到同名文件 Fluent 会停下来问，后台没人回答就卡住。
- 瞬态用 `/solve/dual-time-iterate <时间步数> <每步最多迭代次数>`，稳态用 `/solve/iterate <次数>`。
- 自动保存建议开着，从机被 Windows 更新重启时还能从存档接着算。
- **最后一行必须是 `/exit yes`**：不写的话 Fluent 算完会一直停在提示符，不退出，还占着核。
- `menkou` 是 2022 R1，打不开 2024 R1 存的 case。

## 约定（必须遵守）

1. 只在自己确认过的保存地址里读写。sjh 的文件夹和别人的文件都不要动。
2. `limian` 只用 idle 优先级（默认就是），不要加 `--prio below/normal/above/high`。
3. 结束任务一律用 `node.py stop`。不要按进程名杀 `fl_mpi*`、`fluent` 等进程，那样会连同一台机器上别人的 Fluent 一起杀掉。别人的进程（DMol3 等）不要碰。
4. 派大任务前先 `info`。某台 CPU 已经很满或有 COMSOL 在跑，先提醒用户，或者换一台。
5. 不要重启从机，不要改从机的系统设置，不要在从机上装卸软件。
6. 往回传文件只有约 3 MB/s，只拉需要的结果，大文件挑晚上拉。

更多说明（每条命令的细节、注意事项、Fluent 安装路径）见 `references/usage.md`。
