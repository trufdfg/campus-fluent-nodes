# campus-fluent-nodes

一个 Claude Code / Codex skill：在自己的电脑上，通过 SSH 使用校园网里的三台 Windows 计算从机（`n5950x`、`limian`、`menkou`）跑 Fluent。功能包括检查连通、传文件、后台开算、查看和停止任务、取回结果。

**本仓库不含任何密钥或密码。** 登录从机用的私钥 `wb_nodes` 由 sjh 单独发给你，不要提交到任何仓库。

## 安装

需要：Windows 10/11，连着校园网（IP 是 172.24.x.x）；Python 3.8 以上；系统自带的 OpenSSH 客户端。

把仓库放进 skill 目录，二选一：

```powershell
# 用 Claude Code
git clone https://github.com/trufdfg/campus-fluent-nodes "$env:USERPROFILE\.claude\skills\campus-fluent-nodes"
# 用 Codex
git clone https://github.com/trufdfg/campus-fluent-nodes "$env:USERPROFILE\.codex\skills\campus-fluent-nodes"
```

没装 git 的话，在网页上点 Code > Download ZIP，解压后把文件夹改名为 `campus-fluent-nodes`，放到上面的位置。

## 部署

先把 sjh 发的 `wb_nodes` 放到 `%USERPROFILE%\.ssh\wb_nodes`，然后打开 Claude Code 或 Codex，对它说"部署从机"。它会按 [SKILL.md](SKILL.md) 一步步做：

1. 检查 Python 和 ssh；
2. 生成连接配置（`node.py refresh`）；
3. 逐台检查能不能接通（`node.py check`）；
4. 列出每台建议的文件保存地址，**逐台问你确认**（`node.py roots`）；
5. 显示三台的状态（`node.py info`）。

不用 AI 的话，按 [SKILL.md](SKILL.md) 的"第一次使用：部署"手动执行这些命令也一样。

## 使用

部署好以后直接对 AI 说要做什么，例如"把 D:\cases\a.cas.h5 放到 n5950x 上用 8 核算 240 个时间步"。命令和 journal 的写法见 [SKILL.md](SKILL.md)，细节见 [references/usage.md](references/usage.md)。

这几台从机还有别人在用，请遵守 SKILL.md 里的"约定"。有问题找 sjh。
