#!/usr/bin/env python3
"""hub — 接入市面上的常见 agent CLI,统一搜索、运行、调参(模型/思考强度/权限模式)。

零依赖(Python 3.8+ stdlib)。与 bin/agctl.py 同属 antigravity-control 插件;
antigravity 作为其中一个特殊适配器(走 swarm 看板协议)。

命令:
  hub scan                 检测本机已接入的 agent(含 hermes 多 profile)
  hub search [关键词]      在已知 agent 目录库中搜索(含未安装的,带安装方法)
  hub models <agent>       列出该 agent 可选的模型与思考强度档位
  hub help <agent>         查看该 agent 自己的 --help(核实旗标)
  hub run <agent> "<prompt>" [--model M] [--effort E] [--mode read|workspace|yolo]
                 [--cwd DIR] [--profile P] [--timeout S] [--bg] [--dry] [--yes]
                           用选定参数运行一次 agent 任务
  hub tasks                后台任务列表
  hub output <id> [--tail N] [--wait [S]]
                           查看/等待后台任务输出
  hub stop <id>            终止后台任务

安全:--mode yolo 需要同时给 --yes;--dry 只打印将执行的命令。
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

PLUGIN_BIN = Path(__file__).resolve().parent
AGCTL = PLUGIN_BIN / "agctl.py"
TASKS_DIR = Path.home() / ".agent-hub" / "tasks"

# ---------------------------------------------------------------- 知识库
# verified=True: 旗标已在本机用 --help/实测核实
# verified=False: 目录库条目,旗标为公开文档常见用法,使用前可 `hub help <id>` 核实

CATALOG = [
    {
        "id": "claude", "name": "Claude Code", "vendor": "Anthropic",
        "binaries": ["claude"],
        "install": "npm i -g @anthropic-ai/claude-code",
        "verified": True,
        "argv": ["claude", "-p", "{prompt}"],
        "model": ["--model", "{model}"],
        "effort": ["--effort", "{effort}"],
        "efforts": ["low", "medium", "high", "xhigh", "max"],
        "modes": {
            "read": [],
            "workspace": ["--permission-mode", "acceptEdits"],
            "yolo": ["--dangerously-skip-permissions"],
        },
        "models": ["sonnet", "opus", "haiku", "fable"],
        "model_note": "别名(opus/sonnet/haiku/fable)或完整模型 ID 均可",
        "notes": "非交互用 -p;首次 workspace trust 弹窗在 -p 下自动跳过",
    },
    {
        "id": "hermes", "name": "Hermes Agent", "vendor": "local (~/.hermes)",
        "binaries": ["hermes"],
        "install": "本机已装;profiles 见 hermes-* 伪 agent",
        "verified": True,
        "argv": ["hermes", "-z", "{prompt}"],
        "model": ["-m", "{model}"],
        "effort": ["--reasoning", "{effort}"],
        "efforts": ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"],
        "modes": {"read": [], "workspace": [], "yolo": ["--yolo"]},
        "models": [],
        "model_note": "任意 provider/model 字符串;或直接用 hermes-<profile> 伪 agent",
        "cwd_flag": ["--in", "{cwd}"],
        "notes": "-z 一次性执行;profile 包装脚本在 ~/.local/bin(hermes -p <profile>)",
    },
    {
        "id": "antigravity", "name": "Google Antigravity", "vendor": "Google",
        "binaries": [],  # 特殊:检测 app 进程 + agctl
        "install": "/Applications/Antigravity.app",
        "verified": True,
        "special": "antigravity",
        "models": ["gemini-3-pro", "gemini-3.8-flash"],
        "model_note": "模型名内嵌思考档位后缀(如 gemini-3.8-flash-high);"
                      "--effort 会在现有 desired_model 上替换 -low/-medium/-high 后缀",
        "efforts": ["low", "medium", "high"],
        "modes": {"read": [], "workspace": [], "yolo": []},
        "notes": "run = 向 swarm 看板 @coordinator 发消息(真实驱动 agent);"
                 "需要运行中的 swarm,否则报错提示",
    },
    {
        "id": "codex", "name": "OpenAI Codex CLI", "vendor": "OpenAI",
        "binaries": ["codex"],
        "install": "npm i -g @openai/codex",
        "verified": False,
        "argv": ["codex", "exec", "{prompt}"],
        "model": ["-m", "{model}"],
        "effort": ["-c", "model_reasoning_effort={effort}"],
        "efforts": ["minimal", "low", "medium", "high", "xhigh"],
        "modes": {
            "read": ["--sandbox", "read-only"],
            "workspace": ["--sandbox", "workspace-write"],
            "yolo": ["--dangerously-bypass-approvals-and-sandbox"],
        },
        "models": ["gpt-5.1-codex", "gpt-5.1-codex-max", "gpt-5-codex"],
        "notes": "未在本机核实;先 hub help codex",
    },
    {
        "id": "gemini", "name": "Gemini CLI", "vendor": "Google",
        "binaries": ["gemini"],
        "install": "npm i -g @google/gemini-cli",
        "verified": False,
        "argv": ["gemini", "-p", "{prompt}"],
        "model": ["-m", "{model}"],
        "effort": None,
        "efforts": [],
        "effort_note": "无统一 effort 旗标;用 -m 选带思考档位的模型变体",
        "modes": {"read": [], "workspace": ["--approval-mode", "auto_edit"],
                  "yolo": ["--approval-mode", "yolo"]},
        "models": ["gemini-3-pro-preview", "gemini-3-flash-preview", "gemini-2.5-pro"],
        "notes": "未在本机核实;先 hub help gemini",
    },
    {
        "id": "qwen", "name": "Qwen Code", "vendor": "Alibaba",
        "binaries": ["qwen"],
        "install": "npm i -g @qwen-code/qwen-code",
        "verified": False,
        "argv": ["qwen", "-p", "{prompt}"],
        "model": ["-m", "{model}"],
        "effort": None, "efforts": [],
        "modes": {"read": [], "workspace": ["--approval-mode", "auto_edit"],
                  "yolo": ["--approval-mode", "yolo"]},
        "models": ["qwen3-coder-plus", "qwen3-coder-flash"],
        "notes": "gemini-cli 分支;未在本机核实",
    },
    {
        "id": "iflow", "name": "iFlow CLI", "vendor": "心流/iFlow",
        "binaries": ["iflow"],
        "install": "npm i -g @iflow-ai/iflow-cli",
        "verified": False,
        "argv": ["iflow", "-p", "{prompt}"],
        "model": ["-m", "{model}"],
        "effort": None, "efforts": [],
        "modes": {"read": [], "workspace": ["--approval-mode", "auto_edit"],
                  "yolo": ["--approval-mode", "yolo"]},
        "models": ["Qwen3-Coder", "Kimi-K2", "DeepSeek-V3.1"],
        "notes": "gemini-cli 分支;未在本机核实",
    },
    {
        "id": "cursor-agent", "name": "Cursor CLI", "vendor": "Cursor",
        "binaries": ["cursor-agent"],
        "install": "curl https://cursor.com/install | bash",
        "verified": False,
        "argv": ["cursor-agent", "-p", "{prompt}"],
        "model": ["--model", "{model}"],
        "effort": None, "efforts": [],
        "modes": {"read": [], "workspace": [], "yolo": ["--yolo"]},
        "models": ["composer-1", "claude-4.5-sonnet", "gpt-5"],
        "notes": "未在本机核实;先 hub help cursor-agent",
    },
    {
        "id": "opencode", "name": "OpenCode", "vendor": "SST",
        "binaries": ["opencode"],
        "install": "npm i -g opencode-ai",
        "verified": False,
        "argv": ["opencode", "run", "{prompt}"],
        "model": ["-m", "{model}"],
        "effort": None, "efforts": [],
        "modes": {"read": [], "workspace": [], "yolo": []},
        "models": ["anthropic/claude-sonnet-4-5", "openai/gpt-5"],
        "notes": "模型为 provider/model 格式;未在本机核实",
    },
    {
        "id": "droid", "name": "Factory Droid", "vendor": "Factory",
        "binaries": ["droid"],
        "install": "curl -fsSL https://app.factory.ai/cli | sh",
        "verified": False,
        "argv": ["droid", "exec", "{prompt}"],
        "model": ["-m", "{model}"],
        "effort": None, "efforts": [],
        "modes": {"read": [], "workspace": ["-s", "medium"], "yolo": ["-s", "high"]},
        "models": ["factory-agent", "claude-sonnet-4-5"],
        "notes": "未在本机核实",
    },
    {
        "id": "crush", "name": "Crush", "vendor": "Charm",
        "binaries": ["crush"],
        "install": "brew install charmbracelet/tap/crush",
        "verified": False,
        "argv": ["crush", "run", "{prompt}"],
        "model": ["-m", "{model}"],
        "effort": None, "efforts": [],
        "modes": {"read": [], "workspace": [], "yolo": ["--yolo"]},
        "models": [],
        "notes": "模型为 provider/model 格式;未在本机核实",
    },
    {
        "id": "aider", "name": "Aider", "vendor": "Aider",
        "binaries": ["aider"],
        "install": "python3 -m pip install aider-chat",
        "verified": False,
        "argv": ["aider", "--message", "{prompt}", "--no-auto-commits", "--yes-always"],
        "model": ["--model", "{model}"],
        "effort": None, "efforts": [],
        "modes": {"read": [], "workspace": [], "yolo": []},
        "models": [],
        "model_note": "litellm 格式,如 claude-sonnet-4-5 / gpt-5 / deepseek/deepseek-chat",
        "notes": "编辑型 agent,建议在 git 仓库内使用;未在本机核实",
    },
    {
        "id": "copilot", "name": "GitHub Copilot CLI", "vendor": "GitHub",
        "binaries": ["copilot"],
        "install": "npm i -g @github/copilot",
        "verified": False,
        "argv": ["copilot", "-p", "{prompt}"],
        "model": ["--model", "{model}"],
        "effort": None, "efforts": [],
        "modes": {"read": [], "workspace": [], "yolo": ["--allow-all-tools", "--allow-all-paths"]},
        "models": ["claude-sonnet-4.5", "gpt-5"],
        "notes": "未在本机核实",
    },
    {
        "id": "goose", "name": "Goose", "vendor": "Block",
        "binaries": ["goose"],
        "install": "brew install block-goose",
        "verified": False,
        "argv": ["goose", "run", "--text", "{prompt}"],
        "model": ["--model", "{model}"],
        "effort": None, "efforts": [],
        "modes": {"read": [], "workspace": [], "yolo": []},
        "models": [],
        "notes": "未在本机核实",
    },
    {
        "id": "magpie", "name": "Magpie(模型路由网关)", "vendor": "local",
        "binaries": ["magpie"],
        "install": "本机已装(~/.local/bin/magpie)",
        "verified": True,
        "special": "note-only",
        "notes": "不是任务 runner:它是给各 agent 统一挑模型的网关/GUI,"
                 "与本 hub 互补;`magpie tui` 或 `magpie web --gateway` 管理",
        "models": [], "efforts": [],
        "modes": {},
    },
]

EFFORT_SUFFIX = {"low": "-low", "medium": "-medium", "high": "-high"}


# ---------------------------------------------------------------- 检测

def which(name):
    return shutil.which(name)


def bin_version(path):
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=15)
        out = (r.stdout or r.stderr).strip().splitlines()
        return out[0][:60] if out else None
    except Exception:
        return None


def hermes_profiles():
    """profile 包装脚本(~/.local/bin/hermes-xxx 与 hermes -p <name>)+ profile 目录。"""
    profiles = {}
    lb = Path.home() / ".local" / "bin"
    if lb.is_dir():
        for p in lb.iterdir():
            if not p.is_file():
                continue
            try:
                head = p.read_text(errors="replace")[:400]
            except Exception:
                continue
            m = re.search(r"hermes\s+-p\s+([A-Za-z0-9_.-]+)", head)
            if m:
                profiles.setdefault(m.group(1), str(p))
    ph = Path.home() / ".hermes" / "hermes-agent" / ".hermes"
    if ph.is_dir():
        for d in ph.iterdir():
            if d.is_dir() and (d / "config.yaml").is_file() and d.name not in profiles:
                profiles[d.name] = None  # 有 profile 但没有包装脚本
    return profiles


def detect_all():
    found = []
    for e in CATALOG:
        entry = dict(e)
        entry["installed"] = False
        entry["path"] = None
        entry["version"] = None
        entry["profiles"] = None
        if e.get("special") == "antigravity":
            r = subprocess.run(["pgrep", "-f", r"Antigravity\.app/Contents/MacOS/Antigravity"],
                               capture_output=True)
            entry["installed"] = r.returncode == 0 and AGCTL.is_file()
            entry["path"] = str(AGCTL) if AGCTL.is_file() else None
            entry["version"] = antigravity_version()
        elif e.get("special") == "note-only":
            p = which(e["binaries"][0]) if e["binaries"] else None
            entry["installed"] = bool(p)
            entry["path"] = p
            if p:
                entry["version"] = bin_version(p)
        else:
            p = which(e["binaries"][0]) if e["binaries"] else None
            entry["installed"] = bool(p)
            entry["path"] = p
            if p:
                entry["version"] = bin_version(p)
            if e["id"] == "hermes" and entry["installed"]:
                entry["profiles"] = sorted(hermes_profiles())
        found.append(entry)
    return found


def antigravity_version():
    try:
        r = subprocess.run(["plutil", "-extract", "CFBundleShortVersionString", "raw",
                            "/Applications/Antigravity.app/Contents/Info.plist"],
                           capture_output=True, text=True)
        return r.stdout.strip() or None
    except Exception:
        return None


def find_entry(agent_id):
    for e in CATALOG:
        if e["id"] == agent_id:
            return e
    return None


def resolve_agent(agent_id):
    """返回 (entry, profile)。支持 hermes-<profile> 伪 agent 与已注册 id。"""
    e = find_entry(agent_id)
    if e:
        return e, None
    m = re.match(r"^hermes-(.+)$", agent_id)
    if m:
        prof = m.group(1)
        profs = hermes_profiles()
        if prof in profs:
            e = find_entry("hermes")
            return e, prof
        die("unknown hermes profile %r; found: %s" % (prof, ", ".join(sorted(profs))))
    die("unknown agent %r; 用 `hub scan` 看本机已接入,`hub search` 搜目录库" % agent_id)


# ---------------------------------------------------------------- run

def die(msg, code=1):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False) if is_json()
          else "hub: " + msg, file=sys.stderr)
    sys.exit(code)


def is_json():
    return "--json" in sys.argv


def build_argv(entry, profile, prompt, model, effort, mode, cwd):
    if entry.get("special") == "antigravity":
        return None  # 特殊路径,单独处理
    base = list(entry["argv"])
    exe = entry["binaries"][0]
    if profile:
        wrapper = hermes_profiles().get(profile)
        if wrapper:
            base = [wrapper] + base[1:]
        else:
            base = [exe, "-p", profile] + base[1:]
    # 用绝对路径提高可靠性
    if not profile and which(exe):
        base[0] = which(exe)
    if model:
        if not entry.get("model"):
            die("%s 不支持 --model 旗标(%s)" % (entry["id"], entry.get("model_note", "")))
        base += [x.replace("{model}", model) for x in entry["model"]]
    if effort:
        if not entry.get("effort"):
            die("%s 不支持独立思考强度旗标。%s" % (
                entry["id"], entry.get("effort_note", "")))
        if entry["efforts"] and effort not in entry["efforts"]:
            die("%s 思考强度可选:%s(给了 %r)" % (entry["id"], ", ".join(entry["efforts"]), effort))
        base += [x.replace("{effort}", effort) for x in entry["effort"]]
    if mode != "read":
        mflags = entry.get("modes", {}).get(mode)
        if mflags is None:
            die("%s 不支持 --mode %s;可选:read%s" % (
                entry["id"], mode,
                "".join("/" + k for k in entry.get("modes", {}) if k != "read")))
        if mode == "yolo":
            base += mflags
        else:
            base += mflags
    if cwd and entry.get("cwd_flag"):
        base += [x.replace("{cwd}", cwd) for x in entry["cwd_flag"]]
    out = []
    for a in base:
        out.append(a.replace("{prompt}", prompt))
    return out


def antigravity_plan(prompt, model, effort, mode):
    """返回 antigravity 的执行说明argv(agctl 调用序列)。"""
    steps = []
    if model or effort:
        steps.append(["python3", str(AGCTL), "agent", "coordinator", "model",
                      antigravity_model(effort, model), "--yes"])
    steps.append(["python3", str(AGCTL), "send", prompt, "--to", "coordinator", "--yes"])
    return steps


def antigravity_model(effort, model):
    """确定 Antigravity desired_model:显式 --model 优先;否则现有模型换档位后缀。"""
    if model:
        return model
    base = "gemini-3.8-flash"  # 兜底
    try:
        r = subprocess.run(["python3", str(AGCTL), "agents", "--json"],
                           capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout)
        cur = data["members"]["coordinator"].get("desired_model")
        if cur:
            base = re.sub(r"-(low|medium|high)$", "", cur)
    except Exception:
        pass
    return base + EFFORT_SUFFIX.get(effort or "high", "-high")


def cmd_run(args):
    if not args.pos:
        die("usage: hub run <agent> \"<prompt>\" [options]")
    args.agent = args.pos[0]
    entry, profile = resolve_agent(args.agent)
    prompt = " ".join(args.text).strip()
    if not prompt:
        die("empty prompt; usage: hub run <agent> \"<prompt>\" [options]")
    mode = args.mode or "workspace"
    if mode == "yolo" and not args.yes:
        die("--mode yolo 需要同时给 --yes(跳过所有权限确认属于高危操作)")

    if entry.get("special") == "antigravity":
        steps = antigravity_plan(prompt, args.model, args.effort, mode)
        if args.json:
            jout({"ok": True, "agent": "antigravity", "dry": bool(args.dry),
                  "steps": [" ".join(s) for s in steps]})
        if args.dry:
            print("DRY — 将执行:")
            for s in steps:
                print("  " + " ".join(s))
            return
        for s in steps:
            r = subprocess.run(s, capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                die("step failed: %s\n%s" % (" ".join(s), r.stderr.strip()))
        print("已提交到 Antigravity swarm 看板(被 @ 的 agent 会在下个轮询唤醒)")
        return

    if entry["binaries"] and not which(entry["binaries"][0]):
        die("%s 未安装。安装:%s(或 `hub search %s` 查看详情)"
            % (args.agent, entry.get("install", "?"), args.agent))

    argv = build_argv(entry, profile, prompt, args.model, args.effort, mode, args.cwd)
    if args.dry:
        if args.json:
            jout({"ok": True, "agent": args.agent, "dry": True, "argv": argv,
                  "cwd": args.cwd})
        else:
            print("DRY — " + " ".join(argv) + ("" if not args.cwd else "   (cwd=%s)" % args.cwd))
        return

    t0 = time.time()
    meta = {"id": None, "agent": args.agent, "argv": argv, "cwd": args.cwd,
            "mode": mode, "model": args.model, "effort": args.effort}
    if args.bg:
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        tid = "%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:6])
        log_path = TASKS_DIR / (tid + ".log")
        meta_path = TASKS_DIR / (tid + ".json")
        meta["id"] = tid
        meta["log"] = str(log_path)
        meta["started"] = time.strftime("%Y-%m-%d %H:%M:%S")
        meta["done"] = None
        with open(log_path, "w") as lf, open(meta_path, "w") as mf:
            p = subprocess.Popen(argv, stdout=lf, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL,
                                 cwd=args.cwd or None,
                                 start_new_session=True)
            meta["pid"] = p.pid
            mf.write(json.dumps(meta, ensure_ascii=False, indent=2))
        if args.json:
            jout({"ok": True, "task": meta})
        else:
            print("后台任务 %s 已启动(pid %s)\n查看:hub output %s --wait" % (tid, meta["pid"], tid))
        return

    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL,
                           timeout=args.timeout or 600, cwd=args.cwd or None)
        dur = round(time.time() - t0, 1)
        text = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if args.json:
            jout({"ok": r.returncode == 0, "agent": args.agent, "exit_code": r.returncode,
                  "duration_s": dur, "argv": argv, "output": text,
                  "stderr": err[:2000]})
        else:
            if text:
                print(text)
            if err:
                print("--- stderr ---", file=sys.stderr)
                print(err[:2000], file=sys.stderr)
            if r.returncode != 0:
                sys.exit(r.returncode)
    except subprocess.TimeoutExpired:
        die("timeout after %ss;长任务改用 --bg(后台运行, hub output <id> --wait 收取)"
            % (args.timeout or 600))


def cmd_scan(args):
    found = detect_all()
    if args.json:
        jout({"ok": True, "agents": found})
        return
    print("本机已接入的 agent:")
    for e in found:
        if not e["installed"]:
            continue
        line = "  %-16s %-28s %s" % (e["id"], e["name"],
                                     (e["version"] or "")[:28])
        print(line)
        if e.get("profiles"):
            print("      profiles: %s(可直接 hub run hermes-<profile>)" % ", ".join(e["profiles"]))
        if e.get("special"):
            print("      %s" % e["notes"])
    missing = [e["id"] for e in found if not e["installed"]]
    print("\n未安装(目录库可搜):%s" % ", ".join(missing))
    print("搜详情: hub search <关键词>   搜到后按 install 字段安装即可接入")


def cmd_search(args):
    kw = (" ".join(args.pos).strip().lower()) if args.pos else ""
    found = detect_all()
    inst = {e["id"]: e for e in found}
    hits = []
    for e in CATALOG:
        blob = json.dumps(e, ensure_ascii=False).lower()
        if kw and kw not in blob:
            continue
        hits.append((e, inst[e["id"]]["installed"]))
    if args.json:
        jout({"ok": True, "query": kw, "hits": [
            {"id": e["id"], "name": e["name"], "vendor": e["vendor"],
             "installed": ins, "install": e.get("install"),
             "models": e.get("models"), "efforts": e.get("efforts"),
             "notes": e.get("notes")} for e, ins in hits]})
        return
    if not hits:
        print("目录库中没有匹配 %r 的 agent" % kw)
        return
    print("搜索结果(%d):" % len(hits))
    for e, ins in hits:
        tag = "已接入" if ins else "未安装"
        print("  [%s] %-14s %-22s vendor=%s" % (tag, e["id"], e["name"], e["vendor"]))
        if not ins and e.get("install"):
            print("        安装: %s" % e["install"])
        if e.get("models"):
            print("        常见模型: %s" % ", ".join(e["models"][:4]))
        if e.get("efforts"):
            print("        思考强度: %s" % ", ".join(e["efforts"]))
        if e.get("notes"):
            print("        %s" % e["notes"])


def cmd_models(args):
    agent_id = args.pos[0] if args.pos else die("usage: hub models <agent>")
    entry, profile = resolve_agent(agent_id)
    data = {"ok": True, "agent": agent_id, "models": entry.get("models"),
            "model_note": entry.get("model_note", "任意字符串均可,以官方文档为准"),
            "efforts": entry.get("efforts"),
            "effort_note": entry.get("effort_note"),
            "verified": entry.get("verified", False)}
    if agent_id == "hermes" or agent_id.startswith("hermes-"):
        data["profiles"] = sorted(hermes_profiles())
    if entry.get("special") == "antigravity":
        try:
            r = subprocess.run(["python3", str(AGCTL), "agents", "--json"],
                               capture_output=True, text=True, timeout=15)
            mem = json.loads(r.stdout)["members"]
            data["current_desired_model"] = {k: v.get("desired_model")
                                             for k, v in mem.items()}
        except Exception:
            pass
    if args.json:
        jout(data)
        return
    print("%s(%s)" % (entry["name"], agent_id))
    print("  模型: %s" % (", ".join(entry.get("models")) or "(自由字符串)"))
    if entry.get("model_note"):
        print("    %s" % entry["model_note"])
    if entry.get("efforts"):
        print("  思考强度: %s" % ", ".join(entry["efforts"]))
    if entry.get("effort_note"):
        print("    %s" % entry["effort_note"])
    if data.get("current_desired_model"):
        print("  Antigravity 当前模型: %s" % data["current_desired_model"])
    if not entry.get("verified"):
        print("  注意: 该 agent 旗标未在本机核实,可先 `hub help %s`" % agent_id)


def cmd_help_agent(args):
    agent_id = args.pos[0] if args.pos else die("usage: hub help <agent>")
    entry, profile = resolve_agent(agent_id)
    if entry.get("special"):
        print(entry.get("notes", ""))
        return
    exe = which(entry["binaries"][0])
    if not exe:
        die("%s 未安装" % agent_id)
    r = subprocess.run([exe, "--help"], capture_output=True, text=True, timeout=20)
    print(r.stdout or r.stderr)


def load_task(tid):
    mp = TASKS_DIR / (tid + ".json")
    if not mp.is_file():
        die("no such task: %s(hub tasks 查看)" % tid)
    return json.loads(mp.read_text()), mp


def task_alive(meta):
    pid = meta.get("pid")
    if not pid or meta.get("done"):
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def cmd_tasks(args):
    out = []
    if TASKS_DIR.is_dir():
        for mp in sorted(TASKS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime,
                         reverse=True):
            meta = json.loads(mp.read_text())
            meta["running"] = task_alive(meta)
            out.append(meta)
    if args.json:
        jout({"ok": True, "tasks": out})
        return
    if not out:
        print("(no background tasks)")
        return
    for m in out:
        print("%s  %-14s %-8s %s" % (m["id"], m["agent"],
                                     "running" if m["running"] else "done",
                                     m.get("started", "")))


def cmd_output(args):
    tid = args.pos[0] if args.pos else die("usage: hub output <task-id> [--wait [S]] [--tail N]")
    meta, _ = load_task(tid)
    log = Path(meta["log"])
    deadline = time.time() + (args.wait if args.wait else 0)
    while True:
        if not task_alive(meta) or time.time() >= deadline:
            break
        time.sleep(1.0)
    meta2, _ = load_task(tid)
    if not task_alive(meta2) and not meta2.get("done"):
        meta2["done"] = time.strftime("%Y-%m-%d %H:%M:%S")
        (TASKS_DIR / (tid + ".json")).write_text(
            json.dumps(meta2, ensure_ascii=False, indent=2))
    text = log.read_text(errors="replace") if log.is_file() else ""
    lines = text.splitlines()
    tail = lines[-(args.n or 40):]
    if args.json:
        jout({"ok": True, "task": meta2, "running": task_alive(meta2),
              "output": "\n".join(tail), "total_lines": len(lines)})
        return
    print("--- %s (%s) ---" % (tid, "running" if task_alive(meta2) else "done"))
    for line in tail:
        print(line[:400])


def cmd_stop(args):
    tid = args.pos[0] if args.pos else die("usage: hub stop <task-id>")
    meta, _ = load_task(tid)
    if not task_alive(meta):
        print("task %s 已结束" % tid)
        return
    try:
        os.killpg(os.getpgid(meta["pid"]), signal.SIGTERM)
        print("sent SIGTERM to task %s (pid %s)" % (tid, meta["pid"]))
    except Exception as e:
        die("stop failed: %s" % e)


# ---------------------------------------------------------------- 框架

class Args:
    pass


def jout(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def new_args():
    a = Args()
    a.json = is_json()
    a.yes = False; a.dry = False; a.bg = False; a.wait = 0; a.n = None
    a.agent = None; a.model = None; a.effort = None; a.mode = None
    a.cwd = None; a.timeout = None
    a.pos = []; a.text = []
    return a


USAGE = __doc__


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(USAGE)
        return
    cmd = sys.argv[1]
    rest = sys.argv[2:]
    a = new_args()
    i = 0

    def take(default=None):
        nonlocal i
        i += 1
        return rest[i] if i < len(rest) else default

    while i < len(rest):
        tok = rest[i]
        if tok == "--json":
            pass  # 已在 is_json() 全局读取
        elif tok == "--yes":
            a.yes = True
        elif tok == "--dry":
            a.dry = True
        elif tok == "--bg":
            a.bg = True
        elif tok == "--model":
            a.model = take()
        elif tok == "--effort":
            a.effort = take()
        elif tok == "--mode":
            a.mode = take()
        elif tok == "--cwd":
            a.cwd = os.path.abspath(os.path.expanduser(take("")))
        elif tok == "--timeout":
            a.timeout = int(take("600"))
        elif tok == "--wait":
            nxt = rest[i + 1] if i + 1 < len(rest) else None
            if nxt is not None and nxt.isdigit():
                a.wait = int(nxt)
                i += 1
            else:
                a.wait = 300  # 可选秒数;缺省等 5 分钟
        elif tok == "--tail":
            a.n = int(take("40"))
        elif tok.startswith("--") and tok != "-":
            die("unknown option: %s" % tok)
        else:
            if cmd == "run":
                # 第一个非旗标参数是 agent id,其余全是 prompt 文本
                if not a.pos:
                    a.pos.append(tok)
                else:
                    a.text.append(tok)
            else:
                a.pos.append(tok)
        i += 1
    table = {
        "scan": cmd_scan, "search": cmd_search, "models": cmd_models,
        "help": cmd_help_agent, "run": cmd_run, "tasks": cmd_tasks,
        "output": cmd_output, "stop": cmd_stop,
    }
    fn = table.get(cmd)
    if not fn:
        die("unknown command: %s\n\n%s" % (cmd, USAGE))
    fn(a)


if __name__ == "__main__":
    main()
