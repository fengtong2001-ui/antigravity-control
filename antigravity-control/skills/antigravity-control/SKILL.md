---
name: antigravity-control
description: 查看/控制本机 Google Antigravity —— 它的 swarm 在忙什么、看板消息、给 agent 发任务、启动/停止 agent、打开文件、UI 输入、窗口截图。Use when the user asks what Antigravity is doing, to check its agents/swarm, send a task to Antigravity, control/steer Antigravity, or take its screenshot.
---

# Antigravity Control

控制本机 Google Antigravity(macOS)。核心 CLI:`agctl.py`,零依赖,
位于本 skill 的 base directory 的 `../../bin/agctl.py`(即插件根的 `bin/agctl.py`)。
所有命令都支持 `--json` 输出。写操作默认 dry-run,加 `--yes` 才生效。

先解析真实路径(基于本 skill 加载时给出的 base directory):
`AGCTL="<base-dir>/../../bin/agctl.py"`,运行方式 `python3 "$AGCTL" <command>`。

## 只读(随时可安全执行)

- `python3 "$AGCTL" status` — 应用是否运行、版本、全部会话、swarm 成员与 phase、看板最新消息、交付物、scratch 项目
- `python3 "$AGCTL" agents` — swarm 成员表(role/phase/desired_state/model)
- `python3 "$AGCTL" messages 20` — 最近 20 条看板消息(board.jsonl,含时间与发送者)
- `python3 "$AGCTL" convs` — 全部会话 + steps 统计
- `python3 "$AGCTL" deliver [CONV_ID]` — 交付文件(默认当前 swarm)
- `python3 "$AGCTL" logs 40` — 最新任务/系统日志尾部

## 写操作(写前先告知用户要做什么)

- 发任务/插话:`python3 "$AGCTL" send "请把导出加上 PDF 选项" --to coordinator --yes`
  - `--to NAME` 自动加 `@NAME`;被 @ 的 agent 在下个轮询被唤醒(wake_mode=mentions)
  - 不加 `--yes` 只打印将要写入的内容
- 启停 agent:`python3 "$AGCTL" agent frontend-dev start --yes`(或 `stop`)
  - 直接改 `members.json` 的 desired_state,由 Antigravity 调度器生效
- 打开文件:`python3 "$AGCTL" open /path/to/folder`
- 聚焦:`python3 "$AGCTL" focus`
- UI 输入:`python3 "$AGCTL" type "做点事" --key cmd+l --enter` — 先聚焦,可选按快捷键
  定位输入框,再粘贴文本(假定目标输入框已聚焦/或快捷键能聚焦它);需辅助功能权限
- 截图:`python3 "$AGCTL" screenshot --out /tmp/ag.png` — 需屏幕录制权限,失败会降级全屏

## 直接读原始数据(当 agctl 不足时)

- Swarm 状态:`~/.gemini/antigravity/brain/<conv>/.system_generated/swarm/members.json`、`board.jsonl`
- 会话轨迹:`~/.gemini/antigravity/conversations/<conv>.db`(SQLite,steps 表,WAL —— 读取前把
  `.db/.db-wal/.db-shm` 拷到临时目录)
- 交付物:`~/.gemini/antigravity/brain/<conv>/`(排除 `.system_generated`)

## 注意

- 向运行中的 swarm 写看板会真实影响 agent 行为 —— 发送前向用户复述消息内容
- `type` 依赖 macOS 辅助功能权限;`screenshot` 依赖屏幕录制权限;被拒时提示用户到
  系统设置 → 隐私与安全性 中授权
