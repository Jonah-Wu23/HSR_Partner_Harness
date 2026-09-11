# 本用例的原样复现命令（PowerShell / Git Bash 均可）

cd E:\AI\HSR-Partner-Harness-v0.3.9-logic\evidence\batch-2026-09-10\tools
$env:PYTHONPATH=(Get-Location).Path
& 'E:\AI\HSR Partner Harness\.venv\Scripts\python.exe' run_a12_timeout2.py
# 真实等待 600 秒；期间不做任何裁决
