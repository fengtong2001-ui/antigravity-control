#!/usr/bin/env python3
"""agctl — inspect & control Google Antigravity on the local machine.

Zero-dependency (Python 3.8+ stdlib only). Works on macOS where the
Antigravity app stores its state under ~/.gemini/antigravity/.

Control surfaces used:
  * ~/.gemini/antigravity/brain/<conv>/.system_generated/swarm/  — swarm
    members.json (desired_state) and board.jsonl (message board; the
    runtime tracks per-agent last_read_seq against it, so appending a
    @mention is how agents get woken / receive tasks)
  * conversations/<conv>.db  — per-conversation trajectory databases
  * `open -b com.google.antigravity` — open files/folders in the app
  * AppleScript / System Events — activate, keystrokes, window bounds
  * screencapture — window screenshot

Usage: agctl.py <command> [args] [--json] [--swarm <id-prefix>]
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

HOME_AG = Path.home() / ".gemini" / "antigravity"
CONV_DIR = HOME_AG / "conversations"
BRAIN_DIR = HOME_AG / "brain"
SCRATCH_DIR = HOME_AG / "scratch"
SUMMARY_DB = HOME_AG / "conversation_summaries.db"
APP_PLIST = "/Applications/Antigravity.app/Contents/Info.plist"
BUNDLE_ID = "com.google.antigravity"


# ---------------------------------------------------------------- helpers

def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def die(msg, code=1):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False) if "--json" in sys.argv
          else "agctl: " + msg, file=sys.stderr)
    sys.exit(code)


def jout(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def app_running():
    r = run(["pgrep", "-f", r"Antigravity\.app/Contents/MacOS/Antigravity"])
    pids = [p for p in r.stdout.split() if p.strip()]
    return pids


def app_version():
    try:
        r = run(["plutil", "-extract", "CFBundleShortVersionString", "raw", APP_PLIST])
        return r.stdout.strip() or None
    except Exception:
        return None


def list_convs():
    out = []
    if CONV_DIR.is_dir():
        for db in sorted(CONV_DIR.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
            st = db.stat()
            out.append({
                "id": db.stem,
                "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "size_kb": round(st.st_size / 1024),
                "title": conv_title(db.stem),
            })
    return out


def swarm_dirs():
    if not BRAIN_DIR.is_dir():
        return []
    out = []
    for d in sorted(BRAIN_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        m = d / ".system_generated" / "swarm" / "members.json"
        if m.is_file():
            out.append({"id": d.name, "dir": d, "members_path": m})
    return out


def find_swarm(prefix=None):
    swarms = swarm_dirs()
    if not swarms:
        die("no swarm found under %s — agents may not be running in swarm mode" % BRAIN_DIR)
    if prefix:
        for s in swarms:
            if s["id"].startswith(prefix):
                return s
        die("no swarm id starts with %r" % prefix)
    return swarms[0]  # most recently modified


def load_swarm(prefix=None):
    s = find_swarm(prefix)
    with open(s["members_path"], encoding="utf-8") as f:
        members = json.load(f)
    board_path = s["dir"] / ".system_generated" / "swarm" / "board.jsonl"
    return s, members, board_path


def read_board(board_path):
    entries = []
    if board_path.is_file():
        with open(board_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def conv_title(cid):
    # 1) swarm title
    s = BRAIN_DIR / cid / ".system_generated" / "swarm" / "members.json"
    if s.is_file():
        try:
            with open(s, encoding="utf-8") as f:
                return json.load(f).get("title") or None
        except Exception:
            pass
    # 2) summaries db (copy db+wal+shm to a temp dir so WAL is readable)
    if SUMMARY_DB.is_file():
        try:
            with tempfile.TemporaryDirectory() as td:
                for ext in ("", "-wal", "-shm"):
                    src = Path(str(SUMMARY_DB) + ext)
                    if src.is_file():
                        shutil.copy(src, Path(td) / ("s.db" + ext))
                dbp = Path(td) / "s.db"
                con = sqlite3.connect("file:%s?mode=ro" % dbp, uri=True)
                try:
                    tables = [r[0] for r in con.execute(
                        "select name from sqlite_master where type='table'")]
                    for t in tables:
                        cols = [r[1] for r in con.execute("pragma table_info(%s)" % t)]
                        tcol = next((c for c in cols if "title" in c.lower()), None)
                        idcol = next((c for c in cols
                                      if "conversation" in c.lower() or c.lower() == "id"), None)
                        if tcol and idcol:
                            row = con.execute(
                                "select %s from %s where %s=?" % (tcol, t, idcol),
                                (cid,)).fetchone()
                            if row and row[0]:
                                return str(row[0])
                finally:
                    con.close()
        except Exception:
            pass
    return None


def deliverables(cid):
    d = BRAIN_DIR / cid
    out = []
    if d.is_dir():
        for p in sorted(d.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
            if not p.is_file() or ".system_generated" in p.parts:
                continue
            st = p.stat()
            out.append({
                "path": str(p),
                "name": p.name,
                "size_kb": round(st.st_size / 1024, 1),
                "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
    return out


def conv_db_stats(cid):
    """Copy the conversation DB (WAL!) to a temp dir and read step stats."""
    src = CONV_DIR / (cid + ".db")
    if not src.is_file():
        return None
    try:
        with tempfile.TemporaryDirectory() as td:
            for ext in ("", "-wal", "-shm"):
                p = Path(str(src) + ext)
                if p.is_file():
                    shutil.copy(p, Path(td) / ("c.db" + ext))
            con = sqlite3.connect("file:%s?mode=ro" % (Path(td) / "c.db"), uri=True)
            try:
                total = con.execute("select count(*) from steps").fetchone()[0]
                by_status = dict(con.execute(
                    "select status, count(*) from steps group by status").fetchall())
                last_idx = con.execute("select max(idx) from steps").fetchone()[0]
                return {"steps_total": total, "steps_by_status": by_status,
                        "last_step_idx": last_idx}
            finally:
                con.close()
    except Exception as e:
        return {"error": str(e)}


def tail_task_logs(n, swarm_dir=None):
    """Tail the newest task log and the newest .system_generated/log file."""
    roots = []
    if swarm_dir:
        roots.append(swarm_dir / ".system_generated")
    out = []
    for root in roots:
        for sub in ("tasks", "logs"):
            d = root / sub
            if not d.is_dir():
                continue
            files = [p for p in d.rglob("*") if p.is_file()]
            if not files:
                continue
            newest = max(files, key=lambda p: p.stat().st_mtime)
            try:
                lines = newest.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception as e:
                lines = ["<read error: %s>" % e]
            out.append({"file": str(newest), "tail": lines[-n:]})
    return out


def scratch_projects():
    out = []
    if SCRATCH_DIR.is_dir():
        for d in sorted(SCRATCH_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if d.is_dir():
                out.append({"name": d.name, "path": str(d),
                            "mtime": datetime.fromtimestamp(d.stat().st_mtime)
                            .strftime("%Y-%m-%d %H:%M:%S")})
    return out


# ---------------------------------------------------------------- commands

def cmd_status(args):
    pids = app_running()
    s, members, board_path = load_swarm(args.swarm)
    board = read_board(board_path)
    last = board[-1] if board else None
    cid = s["id"]
    data = {
        "ok": True,
        "app_running": bool(pids),
        "pids": pids,
        "version": app_version(),
        "conversations": list_convs(),
        "swarm": {
            "id": cid,
            "title": members.get("title"),
            "members": {k: {kk: vv for kk, vv in v.items()
                            if kk in ("role", "phase", "desired_state", "model",
                                      "conversation_id", "wake_mode", "killed")}
                        for k, v in members.get("members", {}).items()},
        },
        "board_seq": board[-1]["seq"] if board else 0,
        "last_board_message": last,
        "deliverables": deliverables(cid),
        "scratch_projects": scratch_projects(),
    }
    if args.json:
        jout(data)
        return
    sw = data["swarm"]
    print("Antigravity %s — %s%s" % (
        data["version"] or "?", "running (pid %s)" % pids[0] if pids else "NOT running",
        "" if not pids else ""))
    print()
    print("Swarm: %s (%s)" % (sw["title"] or "(untitled)", cid[:8]))
    for name, m in sorted(sw["members"].items()):
        print("  %-12s %-8s model=%-22s conv=%s" % (
            name, m.get("phase") or m.get("desired_state"),
            m.get("model"), (m.get("conversation_id") or "")[:8]))
    print()
    print("Conversations (%d):" % len(data["conversations"]))
    for c in data["conversations"]:
        print("  %s  %6dKB  %s  %s" % (c["mtime"], c["size_kb"], c["id"][:8],
                                       c["title"] or ""))
    print()
    if last:
        print("Latest board msg (seq %s, by %s @ %s):" % (
            last.get("seq"), last.get("agent"), last.get("time")))
        print("  " + (last.get("text") or "").replace("\n", "\n  ")[:500])
    print()
    if data["deliverables"]:
        print("Deliverables (%d):" % len(data["deliverables"]))
        for d in data["deliverables"][:10]:
            print("  %s  %7sKB  %s" % (d["mtime"], d["size_kb"], d["name"]))
    if data["scratch_projects"]:
        print("Scratch projects: " + ", ".join(p["name"] for p in data["scratch_projects"]))


def cmd_agents(args):
    s, members, _ = load_swarm(args.swarm)
    rows = members.get("members", {})
    if args.json:
        jout({"ok": True, "swarm_id": s["id"], "title": members.get("title"),
              "members": rows})
        return
    print("Swarm %s — %s" % (s["id"][:8], members.get("title") or ""))
    for name, m in rows.items():
        print("  %-14s role=%-10s phase=%-8s desired=%-8s model=%s" % (
            name, m.get("role"), m.get("phase"), m.get("desired_state"), m.get("model")))


def cmd_messages(args):
    s, _, board_path = load_swarm(args.swarm)
    entries = read_board(board_path)
    n = args.n or 10
    entries = entries[-n:]
    if args.json:
        jout({"ok": True, "swarm_id": s["id"], "messages": entries})
        return
    for e in entries:
        print("[seq %s] %s @ %s" % (e.get("seq"), e.get("agent"), e.get("time")))
        print("  " + (e.get("text") or "").replace("\n", "\n  "))
        print()


def cmd_send(args):
    text = " ".join(args.text).strip()
    if not text:
        die("empty message; usage: agctl send \"<text>\" [--to NAME] [--yes]")
    s, members, board_path = load_swarm(args.swarm)
    if args.to:
        mm = members.get("members", {})
        if args.to not in mm:
            die("unknown agent %r; members: %s" % (args.to, ", ".join(mm)))
        text = "@" + args.to + " " + text
    board = read_board(board_path)
    msg = {"seq": (board[-1]["seq"] if board else 0) + 1,
           "agent": args.agent or "zcode",
           "text": text,
           "time": now_str(),
           "request_id": str(uuid.uuid4())}
    if args.yes:
        with open(board_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    else:
        print("DRY RUN — add --yes to actually post to %s" % board_path)
    if args.json:
        jout({"ok": True, "posted": bool(args.yes), "message": msg,
              "board_path": str(board_path),
              "note": "mentioned agent wakes on next poll (wake_mode=mentions)"})
    else:
        print(json.dumps(msg, ensure_ascii=False, indent=2))


def cmd_agent(args):
    if len(args.pos) < 2:
        die("usage: agctl agent <name> <status|start|stop|model [MODEL_ID]> [--yes]")
    name, action = args.pos[0], args.pos[1]
    s, members, _ = load_swarm(args.swarm)
    mm = members.get("members", {})
    if name not in mm:
        die("unknown agent %r; members: %s" % (name, ", ".join(mm)))
    m = mm[name]
    if action == "status":
        if args.json:
            jout({"ok": True, "name": name, "member": m})
        else:
            print(json.dumps(m, ensure_ascii=False, indent=2))
        return
    if action == "model":
        if len(args.pos) < 3 or not args.pos[2]:
            die("usage: agctl agent <name> model <MODEL_ID> [--yes]")
        target = args.pos[2]
        if not args.yes:
            print("DRY RUN — would set %s desired_model -> %s (add --yes)" % (name, target))
            if args.json:
                jout({"ok": True, "dry_run": True, "name": name,
                      "current": m.get("desired_model"), "would_set": target})
            return
        old = m.get("desired_model")
        m["desired_model"] = target
        tmp = Path(str(s["members_path"]) + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(members, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, s["members_path"])
        if args.json:
            jout({"ok": True, "name": name, "old": old, "desired_model": target,
                  "note": "runtime applies desired_model on next scheduler pass"})
        else:
            print("%s: desired_model %s -> %s" % (name, old, target))
        return
    if action not in ("start", "stop"):
        die("action must be status|start|stop|model")
    target = "RUNNING" if action == "start" else "KILLED"
    if not args.yes:
        print("DRY RUN — would set %s desired_state -> %s (add --yes)" % (name, target))
        if args.json:
            jout({"ok": True, "dry_run": True, "name": name,
                  "current": m.get("desired_state"), "would_set": target})
        return
    old = m.get("desired_state")
    m["desired_state"] = target
    tmp = Path(str(s["members_path"]) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(members, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, s["members_path"])
    if args.json:
        jout({"ok": True, "name": name, "old": old, "desired_state": target,
              "note": "the runtime applies desired_state on its next scheduler pass"})
    else:
        print("%s: desired_state %s -> %s" % (name, old, target))


def cmd_deliver(args):
    cid = args.conv
    if not cid:
        s, _, _ = load_swarm(args.swarm)
        cid = s["id"]
    items = deliverables(cid)
    if args.json:
        jout({"ok": True, "conversation": cid, "deliverables": items})
        return
    print("Deliverables in brain/%s:" % cid[:8])
    for d in items:
        print("  %s  %8sKB  %s" % (d["mtime"], d["size_kb"], d["path"]))


def cmd_logs(args):
    s, _, _ = load_swarm(args.swarm)
    logs = tail_task_logs(args.n or 40, s["dir"])
    if args.json:
        jout({"ok": True, "logs": logs})
        return
    for entry in logs:
        print("=== %s (tail %d) ===" % (entry["file"], len(entry["tail"])))
        for line in entry["tail"]:
            print("  " + line[:400])
        print()


def cmd_convs(args):
    convs = list_convs()
    for c in convs:
        c["stats"] = conv_db_stats(c["id"])
    if args.json:
        jout({"ok": True, "conversations": convs})
        return
    for c in convs:
        print("%s  %6dKB  %s" % (c["mtime"], c["size_kb"], c["id"]))
        print("    title: %s" % (c["title"] or "(unknown)"))
        st = c["stats"] or {}
        if "steps_total" in st:
            print("    steps: %s (by status: %s)" % (
                st["steps_total"], st["steps_by_status"]))


def osascript(script):
    env = dict(os.environ)
    return run(["osascript", "-e", script], env=env)


def cmd_open(args):
    path = args.pos[0] if args.pos else None
    if not path:
        projects = scratch_projects()
        if not projects:
            die("no path given and no scratch projects found")
        path = projects[0]["path"]
    p = Path(os.path.abspath(os.path.expanduser(path)))
    if not p.exists():
        die("path does not exist: %s" % p)
    r = run(["open", "-b", BUNDLE_ID, str(p)])
    if r.returncode != 0:
        die("open failed: %s" % r.stderr.strip())
    if args.json:
        jout({"ok": True, "opened": str(p)})
    else:
        print("opened in Antigravity: %s" % p)


def cmd_focus(args):
    r = osascript('tell application id "%s" to activate' % BUNDLE_ID)
    if r.returncode != 0:
        die("activate failed: %s" % r.stderr.strip())
    if args.json:
        jout({"ok": True, "focused": BUNDLE_ID})
    else:
        print("Antigravity activated")


def cmd_type(args):
    text = " ".join(args.text)
    key = args.key
    script = [
        'tell application id "%s" to activate' % BUNDLE_ID,
        "delay 0.4",
    ]
    if key:
        mods, k = [], key
        for mod in ("command", "option", "control", "shift"):
            if mod in key:
                mods.append(mod)
                k = k.replace(mod, "").replace("-", "").strip()
        script.append('tell application "System Events" to keystroke "%s"%s'
                      % (k or "", (" using {%s down}" % ", ".join(m + " down")
                                   if mods else "")))
        script.append("delay 0.3")
    script += [
        'set agctlText to system attribute "AG_AGCTL_TEXT"',
        "set the clipboard to agctlText",
        'tell application "System Events" to keystroke "v" using command down',
        "delay 0.3",
    ]
    if args.enter:
        script.append('tell application "System Events" to keystroke return')
    env = dict(os.environ)
    env["AG_AGCTL_TEXT"] = text
    r = run(["osascript", "-e", " ".join(script)], env=env)
    if r.returncode != 0:
        die("osascript failed (check 系统设置→隐私与安全性→辅助功能 grants access "
            "to the host app): %s" % r.stderr.strip())
    if args.json:
        jout({"ok": True, "typed_len": len(text), "enter": bool(args.enter)})
    else:
        print("typed %d chars%s" % (len(text), " + enter" if args.enter else ""))


def cmd_screenshot(args):
    out = args.out or ("antigravity-%s.png" % time.strftime("%Y%m%d-%H%M%S"))
    out = os.path.abspath(os.path.expanduser(out))
    region = None
    r = osascript(
        'tell application "System Events" to tell (first process whose bundle identifier '
        'is "%s")\nset p to position of window 1\nset s to size of window 1\n'
        'return (item 1 of p as text) & "," & (item 2 of p as text) & "," & '
        '(item 1 of s as text) & "," & (item 2 of s as text)\nend tell' % BUNDLE_ID)
    if r.returncode == 0 and "," in r.stdout.strip():
        region = r.stdout.strip()
    if region:
        r2 = run(["screencapture", "-x", "-R" + region, out])
    else:
        r2 = run(["screencapture", "-x", out])
    if r2.returncode != 0 or not Path(out).is_file():
        die("screencapture failed (check 屏幕录制 permission): %s" % r2.stderr.strip())
    if args.json:
        jout({"ok": True, "out": out, "window_region": region})
    else:
        print("saved: %s%s" % (out, " (window %s)" % region if region else " (full screen)"))


# ---------------------------------------------------------------- arg parse

class Args:
    pass


def parse_send_type(argv, cmd):
    """For send/type: every non-flag token is message text."""
    a = Args()
    a = Args()
    a.json = False; a.swarm = None; a.yes = False; a.n = None; a.conv = None
    a.agent = None; a.to = None; a.key = None; a.enter = False; a.out = None
    a.pos = []; text = []
    it = iter(argv)
    for tok in it:
        if tok == "--json": a.json = True
        elif tok == "--swarm": a.swarm = next(it, None)
        elif tok == "--yes": a.yes = True
        elif tok == "--to": a.to = next(it, None)
        elif tok == "--from": a.agent = next(it, None)
        elif tok == "--key": a.key = next(it, None)
        elif tok == "--enter": a.enter = True
        elif tok == "--out": a.out = next(it, None)
        elif tok == "--n":
            a.n = int(next(it, "10"))
        elif tok.startswith("--") and tok != "-":
            die("unknown option: %s" % tok)
        else:
            text.append(tok)
    a.text = text
    a.cmd = cmd
    return a


USAGE = """agctl — inspect & control Google Antigravity

Commands:
  status                    app + swarm + latest board message overview
  convs                     list conversations (with step stats)
  agents                    list swarm members and phases
  messages [N]              show last N board messages (default 10)
  send "<text>" [--to AGENT] [--from NAME] [--yes]
                            post to the swarm board (@mention wakes the agent);
                            dry-run unless --yes
  agent NAME status|start|stop [--yes]
                            read or set a member's desired_state
  agent NAME model MODEL_ID [--yes]
                            set a member's desired_model (e.g. gemini-3.8-flash-high)
  deliver [CONV_ID]         list deliverable files produced in a conversation
  logs [N]                  tail the newest swarm task/system logs
  open [PATH]               open a file/folder in Antigravity (default: newest scratch project)
  focus                     bring Antigravity to front
  type "<text>" [--key cmd+l] [--enter]
                            activate Antigravity, optional shortcut, paste text
                            (assumes the target input has focus)
  screenshot [--out FILE]   capture the Antigravity window

Global flags: --json (machine readable)   --swarm <id-prefix>
Write operations are dry-run unless --yes is passed.
"""


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(USAGE)
        return
    cmd = sys.argv[1]
    rest = sys.argv[2:]
    if cmd in ("send", "type"):
        args = parse_send_type(rest, cmd)
    elif cmd in ("status", "agents", "messages", "deliver"):
        a = Args()
        a.json = False; a.swarm = None; a.yes = False; a.n = 10; a.conv = None
        a.pos = []; a.text = []; a.agent = None; a.to = None
        a.key = None; a.enter = False; a.out = None
        it = iter(rest)
        for tok in it:
            if tok == "--json": a.json = True
            elif tok == "--swarm": a.swarm = next(it, None)
            elif tok == "--conv": a.conv = next(it, None)
            elif tok.startswith("--") and tok != "-":
                die("unknown option: %s" % tok)
            else:
                try:
                    a.n = int(tok)
                except ValueError:
                    a.pos.append(tok)
        args = a
    elif cmd in ("convs", "logs", "screenshot", "open", "focus", "agent"):
        a = Args()
        a.json = False; a.swarm = None; a.yes = False; a.n = 40; a.conv = None
        a.pos = []; a.text = []; a.agent = None; a.to = None
        a.key = None; a.enter = False; a.out = None
        it = iter(rest)
        for tok in it:
            if tok == "--json": a.json = True
            elif tok == "--swarm": a.swarm = next(it, None)
            elif tok == "--yes": a.yes = True
            elif tok == "--out": a.out = next(it, None)
            elif tok == "--key": a.key = next(it, None)
            elif tok == "--enter": a.enter = True
            elif tok.startswith("--") and tok != "-":
                die("unknown option: %s" % tok)
            else:
                a.pos.append(tok)
        args = a
    else:
        die("unknown command: %s\n\n%s" % (cmd, USAGE))

    table = {
        "status": cmd_status, "convs": cmd_convs, "agents": cmd_agents,
        "messages": cmd_messages, "send": cmd_send, "agent": cmd_agent,
        "deliver": cmd_deliver, "logs": cmd_logs, "open": cmd_open,
        "focus": cmd_focus, "type": cmd_type, "screenshot": cmd_screenshot,
    }
    fn = table.get(cmd)
    if not fn:
        die("no handler for %s" % cmd)
    fn(args)


if __name__ == "__main__":
    main()
