---
description: 搜索/调度本机已接入的 agent(hub:claude、hermes 系列、antigravity 等,可指定模型与思考强度)
argument-hint: "[scan|search <关键词>|models <agent>|run <agent> \"<任务>\" --model M --effort E]"
allowed-tools: Bash
---

# Agent Hub 调度

用本插件的 `bin/hub.py`(本命令文件上两级目录下的 `bin/hub.py`;找不到时
`find ~/.zcode/cli/plugins/cache -name hub.py -path "*antigravity-control*"`)处理用户请求。

用户输入:`$ARGUMENTS`

规则:
1. 意图映射:scan / search 关键词 / models agent / run agent "任务" [--model --effort
   --mode --cwd --bg --dry]。未指定动作默认 `scan`。
2. run 之前先 `models <agent>` 确认模型与 effort 在可选列表内;拿不准先 `--dry`。
3. **yolo 权限档、安装新 agent、向 antigravity 看板发消息**:先向用户复述将要执行的
   命令,得到同意再执行(run yolo 需加 `--yes`)。
4. 预计超过 2 分钟的任务用 `--bg`,之后 `hub output <id> --wait` 收取结果。
5. 用中文汇报:用了哪个 agent/模型/档位、耗时、输出要点、后台任务 id。
