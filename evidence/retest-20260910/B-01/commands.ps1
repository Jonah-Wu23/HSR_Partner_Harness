# 本用例的原样复现命令（PowerShell / Git Bash 均可）

# 1) 启动沙盒
python evidence/retest-20260910/tools/net_sandbox.py --listen 8767 --upstream api.deepseek.com:443 --control 8768 --log <log>
# 2) 以代理环境启动候选
$env:HTTPS_PROXY='http://127.0.0.1:8767'; $env:NO_PROXY='127.0.0.1,localhost'
$env:PAIR_HARNESS_LOG_LEVEL='INFO'
Start-Process desktop/src-tauri/target/release/hsr-partner-harness.exe
# 3) 注入
python evidence/retest-20260910/tools/run_b01_network.py
