from pathlib import Path

p = Path(__file__).with_name("run_b01_network.py")
data = p.read_bytes()
broken = b'HSR-Partner-Harness-v0.3.9-logic\\.tmp\n2-env-backup.env'
fixed = b'HSR-Partner-Harness-v0.3.9-logic\\.tmp\\r2-env-backup.env'
print("broken present:", broken in data)
data = data.replace(broken, fixed)
p.write_bytes(data)
import ast

ast.parse(data.decode("utf-8"))
print("syntax ok")
