
# -*- coding: utf-8 -*-
"""T16 真机批次实时抓取：SQLite 配对状态 diff + sidecar.stderr.log 增量。"""
import json, sqlite3, time, os, datetime, io, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
DB = r"C:\Users\JonahWu\AppData\Local\PairHarness\pair_harness.db"
SIDECAR_LOG = r"C:\Users\JonahWu\AppData\Roaming\com.jonahwu.hsr-partner-harness\sidecar.stderr.log"
OUT = r"E:\AI\HSR Partner Harness\evidence\batch-v0.4.0-real-device\live-capture\capture.log"

def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def read_state():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=2)
    try:
        row = conn.execute("SELECT value FROM app_state WHERE key='remote.pairing_state'").fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()

def summarize(state):
    tokens = [(t.get("device_name"), bool(t.get("revoked")), t.get("token", "")[:8]) for t in state.get("tokens", [])]
    return tokens, state.get("rate_limits", {}), state.get("codes", [])

out = open(OUT, "a", encoding="utf-8")
def w(line):
    out.write(line + "\n")
    out.flush()
    print(line, flush=True)

w(f"=== CAPTURE START {now()} ===")
last_sig = None
last_audit = 0
log_pos = 0
if os.path.exists(SIDECAR_LOG):
    log_pos = os.path.getsize(SIDECAR_LOG)

while True:
    try:
        state = read_state()
        if state is not None:
            audit = state.get("audit", [])
            tokens, rate_limits, codes = summarize(state)
            sig = (len(audit), json.dumps(tokens, sort_keys=True), json.dumps(rate_limits, sort_keys=True), len(codes))
            if sig != last_sig:
                w(f"[{now()}] STATE-CHANGE: audit_n={len(audit)} active_codes={len(codes)} tokens={tokens} rate_limits={json.dumps(rate_limits, ensure_ascii=False)}")
                for e in audit[last_audit:]:
                    w(f"[{now()}]   AUDIT+ {e.get('event')} | {e.get('detail')} | at={e.get('at')}")
                last_audit = len(audit)
                last_sig = sig
    except Exception as exc:
        w(f"[{now()}] POLL-ERROR {type(exc).__name__}: {exc}")
    try:
        if os.path.exists(SIDECAR_LOG):
            size = os.path.getsize(SIDECAR_LOG)
            if size > log_pos:
                with open(SIDECAR_LOG, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(log_pos)
                    chunk = f.read()
                for line in chunk.splitlines():
                    if line.strip():
                        w(f"[{now()}] SIDECAR {line}")
                log_pos = size
            elif size < log_pos:
                log_pos = 0
    except Exception as exc:
        w(f"[{now()}] LOG-ERROR {type(exc).__name__}: {exc}")
    time.sleep(0.5)
