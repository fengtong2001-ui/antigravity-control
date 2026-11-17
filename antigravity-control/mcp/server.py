#!/usr/bin/env python3
"""MCP stdio server for agctl — control Google Antigravity from ZCode or
any other MCP-capable software (Claude Desktop, Cursor, ...).

Protocol: newline-delimited JSON-RPC 2.0 over stdio (MCP stdio transport).
Zero-dependency, Python 3.8+ stdlib only.

Every tool is a thin wrapper over bin/agctl.py (same directory level).
Write-ish tools (ag_send, ag_agent_set, ag_type) default to dry-run /
preview unless confirm=true is passed.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

AGCTL = Path(__file__).resolve().parent.parent / "bin" / "agctl.py"
HUB = Path(__file__).resolve().parent.parent / "bin" / "hub.py"

SERVER_INFO = {"name": "antigravity-control", "version": "0.2.0"}
PROTOCOL_VERSION = "2024-11-05"

BOOL_SCHEMA = {"type": "boolean", "default": False}

TOOLS = [
    {
        "name": "ag_status",
        "description": "Antigravity 总览:应用是否在运行、版本、全部会话、swarm 成员状态、"
                       "看板最新消息、交付物、scratch 项目。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "ag_agents",
        "description": "列出 Antigravity swarm 的成员(agent 名、role、phase、desired_state、model)。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "ag_messages",
        "description": "读取 swarm 看板(board.jsonl)最近 N 条消息,默认 10。",
        "inputSchema": {"type": "object", "properties": {"n": {"type": "integer", "default": 10}}},
    },
    {
        "name": "ag_send",
        "description": "向 swarm 看板发一条消息。@agent名 可以唤醒对应 agent(如 @coordinator)。"
                       "confirm=false 时只预览不写入。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "消息正文"},
                "to": {"type": "string", "description": "可选:目标 agent 名,自动加 @mention"},
                "from": {"type": "string", "description": "可选:发送者名,默认 zcode"},
                "confirm": {**BOOL_SCHEMA, "description": "true 才真正写入看板"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "ag_agent_set",
        "description": "查看或修改 swarm 成员的 desired_state(start=RUNNING, stop=KILLED)。"
                       "confirm=false 时只预览。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "action": {"type": "string", "enum": ["status", "start", "stop"]},
                "confirm": {**BOOL_SCHEMA, "description": "start/stop 需 true 才写入"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "ag_deliverables",
        "description": "列出某会话(默认当前 swarm)在 brain/ 下产出的交付文件。",
        "inputSchema": {"type": "object", "properties": {
            "conversation_id": {"type": "string"}}},
    },
    {
        "name": "ag_logs",
        "description": "尾部查看 swarm 最新的任务/系统日志。",
        "inputSchema": {"type": "object", "properties": {"n": {"type": "integer", "default": 40}}},
    },
    {
        "name": "ag_open",
        "description": "在 Antigravity 中打开文件或文件夹(缺省打开最新 scratch 项目)。",
        "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
    {
        "name": "ag_focus",
        "description": "把 Antigravity 激活到前台。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "ag_type",
        "description": "激活 Antigravity,可选先按一个快捷键(如 cmd+l),然后把文本粘贴到当前"
                       "聚焦的输入框,可选回车发送。confirm=false 时只返回说明不执行。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "key": {"type": "string", "description": "可选快捷键,如 cmd+l"},
                "enter": {**BOOL_SCHEMA, "description": "粘贴后按回车"},
                "confirm": {**BOOL_SCHEMA},
            },
            "required": ["text"],
        },
    },
    {
        "name": "ag_screenshot",
        "description": "截图 Antigravity 窗口(需屏幕录制权限),返回保存路径。",
        "inputSchema": {"type": "object", "properties": {
            "out": {"type": "string", "description": "输出 png 路径"}}},
    },
    {
        "name": "hub_scan",
        "description": "检测本机已接入哪些常见 agent CLI(claude/codex/gemini/hermes 系列/"
                       "antigravity 等),含版本与 hermes profiles。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "hub_search",
        "description": "在市面常见 agent 目录库中搜索(含未安装的,返回安装方法、"
                       "常见模型与思考强度档位)。",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "关键词,如 codex / qwen / 统计"}}},
    },
    {
        "name": "hub_models",
        "description": "列出某 agent 可选的模型与思考强度档位(hermes-* 会附带 profiles,"
                       "antigravity 会附当前各成员 desired_model)。",
        "inputSchema": {"type": "object", "properties": {
            "agent": {"type": "string", "description": "agent id,如 claude / hermes-ting / antigravity"}},
            "required": ["agent"]},
    },
    {
        "name": "hub_run",
        "description": "用指定 agent 执行一次任务。可选 --model(模型)、--effort(思考强度,"
                       "需该 agent 支持)、--mode(read|workspace|yolo 权限档)、--cwd(工作目录)、"
                       "--bg(后台)、--dry(只打印将执行的命令)。mode=yolo 必须同时 confirm=true。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string"},
                "prompt": {"type": "string"},
                "model": {"type": "string"},
                "effort": {"type": "string"},
                "mode": {"type": "string", "enum": ["read", "workspace", "yolo"]},
                "cwd": {"type": "string"},
                "timeout": {"type": "integer", "description": "同步超时秒数,默认 600"},
                "bg": {**BOOL_SCHEMA},
                "dry": {**BOOL_SCHEMA, "description": "true 只返回将要执行的命令"},
                "confirm": {**BOOL_SCHEMA, "description": "yolo 模式必须为 true"},
            },
            "required": ["agent", "prompt"],
        },
    },
    {
        "name": "hub_tasks",
        "description": "列出 hub 后台任务(--bg 启动的)。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "hub_output",
        "description": "查看后台任务输出;wait=true 时等待其结束(最长 300 秒)。",
        "inputSchema": {"type": "object", "properties": {
            "task_id": {"type": "string"},
            "tail": {"type": "integer", "description": "取尾部 N 行,默认 40"},
            "wait": {**BOOL_SCHEMA}},
            "required": ["task_id"]},
    },
    {
        "name": "hub_stop",
        "description": "终止一个后台任务。",
        "inputSchema": {"type": "object", "properties": {
            "task_id": {"type": "string"}}, "required": ["task_id"]},
    },
]


def call_agctl(argv, timeout=30):
    cmd = [sys.executable, str(AGCTL)] + argv
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = p.stdout.strip()
    if p.returncode != 0:
        return "ERROR: %s" % (p.stderr.strip() or out or ("exit %d" % p.returncode))
    return out or "(no output)"


def call_hub(argv, timeout=900):
    cmd = [sys.executable, str(HUB)] + argv
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = p.stdout.strip()
    if p.returncode != 0:
        return "ERROR: %s" % (p.stderr.strip() or out or ("exit %d" % p.returncode))
    return out or "(no output)"


def tool_call(name, args):
    args = args or {}
    if name == "ag_status":
        return call_agctl(["status", "--json"])
    if name == "ag_agents":
        return call_agctl(["agents", "--json"])
    if name == "ag_messages":
        return call_agctl(["messages", "--json", str(int(args.get("n", 10)))])
    if name == "ag_send":
        argv = ["send", args.get("text", "")]
        if args.get("to"):
            argv += ["--to", args["to"]]
        if args.get("from"):
            argv += ["--from", args["from"]]
        if args.get("confirm"):
            argv += ["--yes"]
        argv += ["--json"]
        return call_agctl(argv)
    if name == "ag_agent_set":
        argv = ["agent", args.get("name", ""), args.get("action", "status")]
        if args.get("confirm") and args.get("action") in ("start", "stop"):
            argv += ["--yes"]
        argv += ["--json"]
        return call_agctl(argv)
    if name == "ag_deliverables":
        argv = ["deliver", "--json"]
        if args.get("conversation_id"):
            argv.append(args["conversation_id"])
        return call_agctl(argv)
    if name == "ag_logs":
        return call_agctl(["logs", "--json", str(int(args.get("n", 40)))])
    if name == "ag_open":
        argv = ["open", "--json"]
        if args.get("path"):
            argv.append(args["path"])
        return call_agctl(argv)
    if name == "ag_focus":
        return call_agctl(["focus", "--json"])
    if name == "ag_type":
        if not args.get("confirm"):
            return json.dumps({
                "ok": False, "dry_run": True,
                "would_type": args.get("text", ""),
                "note": "call again with confirm=true to actually type into the "
                        "focused Antigravity input",
            }, ensure_ascii=False)
        argv = ["type", args.get("text", ""), "--json"]
        if args.get("key"):
            argv += ["--key", args["key"]]
        if args.get("enter"):
            argv += ["--enter"]
        return call_agctl(argv)
    if name == "ag_screenshot":
        argv = ["screenshot", "--json"]
        if args.get("out"):
            argv += ["--out", args["out"]]
        return call_agctl(argv)
    if name == "hub_scan":
        return call_hub(["scan", "--json"])
    if name == "hub_search":
        argv = ["search", "--json"]
        if args.get("query"):
            argv.append(args["query"])
        return call_hub(argv)
    if name == "hub_models":
        return call_hub(["models", args.get("agent", ""), "--json"])
    if name == "hub_run":
        argv = ["run", args.get("agent", ""), args.get("prompt", ""),
                "--json"]
        if args.get("model"):
            argv += ["--model", args["model"]]
        if args.get("effort"):
            argv += ["--effort", args["effort"]]
        if args.get("mode"):
            argv += ["--mode", args["mode"]]
        if args.get("cwd"):
            argv += ["--cwd", args["cwd"]]
        if args.get("timeout"):
            argv += ["--timeout", str(int(args["timeout"]))]
        if args.get("bg"):
            argv += ["--bg"]
        if args.get("dry"):
            argv += ["--dry"]
        if args.get("confirm") and args.get("mode") == "yolo":
            argv += ["--yes"]
        timeout = 960 if not args.get("bg") and not args.get("dry") else 30
        return call_hub(argv, timeout=timeout)
    if name == "hub_tasks":
        return call_hub(["tasks", "--json"])
    if name == "hub_output":
        argv = ["output", args.get("task_id", ""), "--json"]
        if args.get("tail"):
            argv += ["--tail", str(int(args["tail"]))]
        if args.get("wait"):
            argv += ["--wait", "300"]
        timeout = 360 if args.get("wait") else 30
        return call_hub(argv, timeout=timeout)
    if name == "hub_stop":
        return call_hub(["stop", args.get("task_id", "")])
    return "ERROR: unknown tool %s" % name


def reply(req_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(req):
    method = req.get("method", "")
    req_id = req.get("id")
    if method == "initialize":
        reply(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    elif method == "ping":
        reply(req_id, {})
    elif method == "tools/list":
        reply(req_id, {"tools": TOOLS})
    elif method == "tools/call":
        params = req.get("params", {})
        name = params.get("name", "")
        try:
            text = tool_call(name, params.get("arguments", {}))
            reply(req_id, {"content": [{"type": "text", "text": text}]})
        except Exception as e:  # noqa: BLE001 — report as tool error
            reply(req_id, {
                "content": [{"type": "text", "text": "ERROR: %s" % e}],
                "isError": True,
            })
    elif req_id is not None:
        reply(req_id, None, {"code": -32601, "message": "method not found: %s" % method})
    # notifications (no id): ignore


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            handle(req)
        except Exception as e:  # noqa: BLE001 — keep the server alive
            if req.get("id") is not None:
                reply(req.get("id"), None, {"code": -32603, "message": str(e)})


if __name__ == "__main__":
    main()
