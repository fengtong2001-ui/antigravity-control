# antigravity-control

在 ZCode(或任何支持 MCP 的软件:Claude Desktop、Cursor 等)里:
1. 直接查看和控制本机 Google Antigravity;
2. 接入市面常见 agent CLI,统一搜索、调度、按需指定**模型 / 思考强度 / 权限档**。

## 两套能力

### A. Antigravity 深度控制(agctl.py)

| 能力 | 命令 |
|---|---|
| 在忙什么(会话/swarm/看板/日志) | `agctl status` / MCP `ag_status` |
| 给 agent 发任务(看板 @mention 唤醒) | `agctl send "..." --to coordinator --yes` |
| 启动/停止某个 agent | `agctl agent <name> start\|stop --yes` |
| **设置某成员的模型** | `agctl agent <name> model gemini-3.8-flash-high --yes` |
| 交付物 / 会话轨迹统计 | `agctl deliver` / `agctl convs` |
| 打开文件 / 聚焦 / UI 输入 / 截图 | `agctl open\|focus\|type\|screenshot` |

原理:Antigravity swarm 用文件协议协调 —— `~/.gemini/antigravity/brain/<conv>/
.system_generated/swarm/board.jsonl`(追加 `{seq,agent,text,time,request_id}` 即发
消息,@名字 唤醒)和 `members.json`(`desired_state`/`desired_model` 由调度器生效)。

### B. 多 Agent 调度中心(hub.py,0.2.0 新增)

| 能力 | 命令 |
|---|---|
| 本机已接入哪些 agent | `hub scan`(自动探测 CLI + hermes profiles + Antigravity) |
| 搜索市面 agent(含未安装) | `hub search codex` → 返回安装方法/模型/档位 |
| 某 agent 的模型与思考强度 | `hub models claude` |
| 派任务(全参数) | `hub run claude "..." --model sonnet --effort high --mode workspace --cwd DIR` |
| 后台任务 | `hub run <agent> "..." --bg` → `hub tasks` / `hub output <id> --wait` / `hub stop <id>` |
| 预演命令不执行 | `hub run <agent> "..." --dry` |

**已核实适配**(本机):claude 2.1.312(`--model`/`--effort low~max`/
`--permission-mode`)、hermes(`-z`/`-m`/`--reasoning none~ultra`,profiles
hermes-ting / hermes-deepseekv4-1 / hermes-gpt6-1terra 自动发现)、antigravity
(看板协议,--effort 映射到模型档位后缀)。
**目录库**(装好即接入,标 `verified:false` 提醒先核实):codex、gemini、qwen、
iflow、cursor-agent、opencode、droid、crush、aider、copilot、goose;另探测
magpie(模型路由网关,与本 hub 互补)。

## 组件

- `bin/agctl.py` — Antigravity 控制核心(零依赖 Python)
- `bin/hub.py` — 多 agent 接入/调度核心(零依赖 Python)
- `mcp/server.py` — MCP stdio server(18 个工具:ag_* 8 个 + hub_* 7 个等)
- `skills/antigravity-control/` — 深度控制 Antigravity 的 agent 说明
- `skills/agent-dispatch/` — 按用户要求选 agent/模型/档位并调度的 agent 说明
- `commands/ag.md`、`commands/hub.md` — 斜杠命令 `/ag`、`/hub`

## 安全

- agctl 写操作默认 dry-run,`--yes` 才生效;hub 的 yolo 权限档必须同时 `--yes`
- MCP 层:hub_run 的 yolo 需要 `confirm: true`
- hub 未安装的 agent 不会静默安装,只提示安装命令

## 权限(macOS)

- 辅助功能(Accessibility):agctl `focus`/`type`/截图取窗口坐标
- 屏幕录制(Screen Recording):agctl `screenshot`
- 各 agent CLI 自身的账号登录由用户事先完成
