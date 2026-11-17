# antigravity-control

**ZCode 插件** — 在 ZCode(或任何支持 MCP 的软件:Claude Desktop、Cursor 等)里:

1. **直接查看与控制本机 Google Antigravity**(Google 的 agentic IDE):
   - 看它的 swarm 多智能体在忙什么(成员/阶段/模型/看板消息/日志/交付物)
   - 给 agent 发任务、启动/停止成员、**改成员模型**
   - 打开文件、聚焦窗口、UI 级输入、窗口截图
2. **接入市面常见 agent CLI,统一调度**(v0.2.0):
   - 自动探测本机已装的 agent(claude、hermes 多 profile、antigravity 等)
   - 目录库搜索常见 agent(codex / gemini / qwen / iflow / cursor-agent / opencode /
     droid / crush / aider / copilot / goose),附安装方法,装好即接入
   - 派任务时自由指定**模型**与**思考强度**(hub 统一 `--effort`,自动映射各家旗标:
     claude `--effort low~max`、hermes `--reasoning none~ultra`、codex
     `-c model_reasoning_effort=…`)与**权限档**(`--mode read|workspace|yolo`)
   - 长任务后台运行:`--bg` → `hub output <id> --wait` / `hub stop <id>`

> 试用环境:macOS + Antigravity 2.32.x。其余平台 Antigravity 部分需自行确认数据目录。

## 在 ZCode 安装(插件市场)

1. **Plugin Marketplace → Add → Add Plugin Marketplace**,粘贴本仓库地址:
   `https://github.com/fengtong2001-ui/antigravity-control`
2. 在市场 **fengtong-public** 中找到 **Antigravity Control + Agent Hub** → **Install**
3. 管理入口:**Settings → Plugins**;装好后可用斜杠命令 `/ag`(控制 Antigravity)、
   `/hub`(调度 agent),或直接让 agent 干活(会自动触发对应 skill)

## 在其他 MCP 软件使用

克隆仓库后,把下面片段加进你的 MCP 配置(Claude Desktop 的
`claude_desktop_config.json` 等),`/path/to/repo` 换成实际克隆路径:

```json
{
  "mcpServers": {
    "antigravity": {
      "command": "/usr/bin/python3",
      "args": ["/path/to/repo/antigravity-control/mcp/server.py"]
    }
  }
}
```

提供 18 个工具:`ag_status / ag_agents / ag_messages / ag_send / ag_agent_set /
ag_deliverables / ag_logs / ag_open / ag_focus / ag_type / ag_screenshot` 与
`hub_scan / hub_search / hub_models / hub_run / hub_tasks / hub_output / hub_stop`。

## 命令行直用(零依赖,Python 3.8+ 标准库)

```bash
# —— Antigravity ——
python3 antigravity-control/bin/agctl.py status          # 它在忙什么
python3 antigravity-control/bin/agctl.py messages 20     # swarm 看板最近 20 条
python3 antigravity-control/bin/agctl.py send "请汇报进度" --to coordinator --yes
python3 antigravity-control/bin/agctl.py agent frontend-dev start --yes
python3 antigravity-control/bin/agctl.py agent frontend-dev model gemini-3-pro-high --yes
python3 antigravity-control/bin/agctl.py screenshot --out /tmp/ag.png

# —— 多 agent 调度 ——
python3 antigravity-control/bin/hub.py scan              # 本机接入了哪些 agent
python3 antigravity-control/bin/hub.py search codex      # 搜目录库(含安装方法)
python3 antigravity-control/bin/hub.py models claude     # 可选模型与思考强度
python3 antigravity-control/bin/hub.py run claude "重构这个函数" \
    --model sonnet --effort high --mode workspace --cwd /path/to/project
python3 antigravity-control/bin/hub.py run hermes-ting "任务" --effort ultra --bg
python3 antigravity-control/bin/hub.py output <任务id> --wait
```

## 工作原理

Antigravity 没有公开控制 API。本插件逆向出它的 swarm 文件协议并直接在协议层操作:

- `~/.gemini/antigravity/brain/<conv>/.system_generated/swarm/board.jsonl` — 看板。
  追加一行 `{seq, agent, text, time, request_id}` 即发消息;被 `@` 的成员按
  `wake_mode=mentions` 唤醒(与 Antigravity 内部 `post_message` 工具同一协议)
- `.../swarm/members.json` — 成员表;改 `desired_state`(RUNNING/KILLED)与
  `desired_model` 即被调度器生效
- 应用层:`open -b com.google.antigravity`、AppleScript(激活/按键)、`screencapture -R`

⚠️ 非官方集成,依赖内部文件格式,Antigravity 大版本更新可能需要适配。

## 安全设计

- agctl 全部写操作默认 **dry-run**,显式 `--yes` 才生效;hub 的 yolo 权限档必须
  同时 `--yes`(MCP 层 `confirm: true`)
- 未安装的 agent 不会静默安装,只提示安装命令
- SQLite 读取前把 WAL 拷到临时目录,不与运行中的应用抢锁

## macOS 权限

- 辅助功能(Accessibility):`focus` / `type` / 窗口截图定位
- 屏幕录制(Screen Recording):`screenshot`
- 各 agent CLI 的账号登录由用户自行完成

## License

MIT
