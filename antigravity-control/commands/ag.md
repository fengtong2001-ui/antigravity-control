---
description: 查看或控制本机 Antigravity(swarm 状态/看板/发消息/启停 agent/打开文件/截图)
argument-hint: "[status|messages|send <text>|agent <name> start|open <path>|screenshot]"
allowed-tools: Bash
---

# Antigravity 控制

用本插件提供的 CLI(位于本命令文件所在插件根的 `bin/agctl.py`)处理用户请求。

用户输入:`$ARGUMENTS`

规则:
1. 解析用户意图映射到 agctl 子命令:status / agents / messages N / deliver / logs / 
   send "<text>" --to <agent> / agent <name> start|stop / open <path> / focus / 
   type "<text>" / screenshot。
2. 未指定动作时默认执行 `status` 并把结果汇报给用户。
3. 只读命令直接执行;**写操作(send/agent/type)先向用户复述将要执行的内容**,
   用户已明确要求(如"发这条消息给 coordinator")才加 `--yes`。
4. 运行方式:`python3 "<插件根>/bin/agctl.py" <子命令> [参数]`;插件根是本命令文件
   上两级目录。找不到文件时用 `find ~/.zcode/cli/plugins/cache -name agctl.py -path "*antigravity-control*"`。
5. 用中文向用户汇报结果要点(消息内容、成员状态变化、文件路径)。
