# 本用例的原样复现命令（PowerShell / Git Bash 均可）

# 沙盒以 --cut-delay 60 启动，唯一触发条件是响应下行 256 字节
cd E:\AI\HSR-Partner-Harness-v0.3.9-logic\evidence\retest-r2-20260910\tools
$env:PYTHONPATH=(Get-Location).Path
& 'E:\AI\HSR-Partner-Harness-v0.3.9-logic\.venv\Scripts\python.exe' run_b01_cut_retry2.py
