#!/usr/bin/env python3
"""wake add <time> <note> [--title T]   queue a wake (time: 'YYYY-MM-DD HH:MM', 'HH:MM' = next one, '+30m' '+2h' '+1d')
wake now <note> [--title T]          wake the agent as soon as it is free
wake list                            show queued wakes
wake cancel <id>                     drop one

Times use plugins.entries.wake.settings.timezone (default: system local).
Route a cron job's output to the agent: hermes cron edit <job> --deliver wake_agent"""
import importlib.util, re, sys
from datetime import datetime, timedelta
from pathlib import Path

spec = importlib.util.spec_from_file_location("wake_engine", Path(__file__).resolve().parent / "engine.py")
eng = importlib.util.module_from_spec(spec); spec.loader.exec_module(eng)
TZ = eng.tz()


def when(s):
    now = datetime.now(TZ)
    if s == "now":
        return now
    if m := re.fullmatch(r"\+(\d+)([mhd])", s):
        return now + timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[m[2]]: int(m[1])})
    if re.fullmatch(r"\d{1,2}:\d{2}", s):
        h, mi = map(int, s.split(":")); t = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        return t if t > now else t + timedelta(days=1)
    return datetime.fromisoformat(s.replace(" ", "T")).replace(tzinfo=TZ)


a = sys.argv[1:]
title = None
if "--title" in a:
    i = a.index("--title"); title = a[i + 1]; del a[i:i + 2]
if not a or a[0] in ("-h", "--help"):
    print(__doc__); sys.exit(0)
if a[0] in ("add", "now"):
    t, note = (when("now"), " ".join(a[1:])) if a[0] == "now" else (when(a[1]), " ".join(a[2:]))
    if not note.strip():
        sys.exit("wake: note is empty")
    item = eng.add_wake(note.strip(), title or note.strip().splitlines()[0], at=t.timestamp())
    print(f"wake {item['id']} at {t:%a %d %b %H:%M}: {item['title']}")
elif a[0] == "list":
    for i in sorted(eng.locked("queue.json", lambda q: (q, q), []), key=lambda i: i["at"]):
        err = f"  [retrying: {i['last_error']}]" if i.get("last_error") else ""
        print(f"{i['id']}  {datetime.fromtimestamp(i['at'], TZ):%a %d %b %H:%M}  {i['title']}{err}")
elif a[0] == "cancel" and len(a) > 1:
    n = eng.locked("queue.json", lambda q: (len(q) - len([i for i in q if i["id"] != a[1]]), [i for i in q if i["id"] != a[1]]), [])
    print("cancelled" if n else "no such wake")
else:
    sys.exit(__doc__)
