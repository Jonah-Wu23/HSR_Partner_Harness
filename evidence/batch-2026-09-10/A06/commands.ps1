# 本用例的原样复现命令（PowerShell / Git Bash 均可）

cd E:\AI\HSR-Partner-Harness-v0.3.9-logic\evidence\batch-2026-09-10\tools
$env:PYTHONPATH=(Get-Location).Path
& 'E:\AI\HSR Partner Harness\.venv\Scripts\python.exe' run_a06.py
# 防火墙规则 S4-A06-block-deepseek 由脚本自建自删；异常退出时手工执行：
Remove-NetFirewallRule -DisplayName 'S4-A06-block-deepseek' -ErrorAction SilentlyContinue
