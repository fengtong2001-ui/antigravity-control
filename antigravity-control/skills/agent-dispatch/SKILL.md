---
name: agent-dispatch
description: 按用户要求挑选并调度本机已接入的 agent(claude、hermes 系列、antigravity、codex、gemini、qwen 等),自由指定模型、思考强度、权限档位。Use when the user asks to 用某个 agent 干活、换 agent、换模型、调思考强度/effort/reasoning、比较不同 agent,或想把任务派给 Claude Code / Codex / Gemini / Antigravity 等执行。
---

# Agent Dispatch(多 agent 调度)

本插件把本机 agent CLI 统一接入 `hub.py`(零依赖)。skill base directory 的
`../../bin/hub.py` 即插件根的 `bin/hub.py`;运行方式 `python3 "$HUB" <命令>`。
所有命令支持 `--json`。

## 命令速查

```bash
HUB="<skill-base>/../../bin/hub.py"
python3 "$HUB" scan                     # 本机已接入哪些 agent(含版本/profiles)
python3 "$HUB" search codex             # 目录库搜索(含未安装 agent + 安装方法)
python3 "$HUB" models claude            # 某 agent 的模型与思考强度档位
python3 "$HUB" help codex               # 用该 agent 自己的 --help 核实旗标
python3 "$HUB" run claude "任务..." --model sonnet --effort high --mode workspace --cwd /path
python3 "$HUB" run hermes-ting "任务..." --effort high   # hermes 多 profile 伪 agent
python3 "$HUB" run antigravity "任务..." --effort high     # 写进 swarm 看板 @coordinator
python3 "$HUB" run codex "任务..." --bg  # 后台跑;tasks/output/stop 收取
```

## 关键语义

- **agent 选择**:scan 结果里的 id。hermes 的多 profile 是伪 agent(`hermes-ting`、
  `hermes-deepseekv4-1`、`hermes-gpt6-1terra`),每个 profile 自带模型;
  antigravity 走 swarm 看板(真实驱动运行中的 swarm)。
- **模型**:hub 已知各 agent 的常见模型清单(`models` 可查);任何 agent 都接受
  自由字符串模型 ID。Antigravity 的模型名内嵌档位(如 `gemini-3.8-flash-high`)。
- **思考强度**:参数名各家不同,hub 统一成 `--effort`,自动映射:
  claude `--effort low|medium|high|xhigh|max`;hermes `--reasoning none~ultra`;
  codex `-c model_reasoning_effort=...`;不支持的 agent 会明确报错并列出可选项。
- **权限档** `--mode`:read(只读) / workspace(允许编辑工作区,默认) / yolo
  (跳过全部确认,**必须用户明确同意后才传,且 hub 要求同时给 --yes**)。
- **--dry**:只打印将要执行的完整命令,不执行。拿不准旗标时先 dry。
- **长任务**:预计 >2 分钟用 `--bg`,然后 `hub output <id> --wait` 收取,
  `hub stop <id>` 终止。

## 选型决策(用户没有指定时)

1. 用户点名了 agent/模型 → 直接用,参数照用户说的来。
2. 用户没点名,按任务特征推荐并**说明理由**,一次只推荐一个主选 + 一个备选:
   - 需要 GUI 级多智能体协作/浏览器调试 → `antigravity`
   - 通用编码,生态稳 → `claude`(模型 sonnet 起步,难题 opus + effort high)
   - 便宜/快速大批量 → `hermes-<profile>`(用户已有 deepseek/gpt/ting 配置)
   - 需要 OpenAI 系模型 → `codex`(未装则给安装命令征求同意)
   - 纯问答/小改动 → effort 用 low/medium;架构/疑难杂症 → high 及以上
3. 用户要求"调参"却没说哪个维度 → 先 `models <agent>` 展示可选项让用户挑。

## 安全与确认

- yolo 模式、安装新 agent、写 Antigravity 看板 —— 先向用户复述将要执行的内容再动手
- 未验证旗标的 agent(目录库 `verified:false`)先 `help <agent>` 或 `--dry` 核实
- 同步 run 超时默认 600s;超时报错会提示改用 --bg

## 深度控制 Antigravity

本 skill 只做调度;要深入控制 Antigravity(看板消息、成员启停、UI 输入、截图),
配合使用同插件的 antigravity-control skill。
