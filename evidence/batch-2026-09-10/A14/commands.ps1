# 本用例的原样复现命令（PowerShell / Git Bash 均可）

cd E:\AI\HSR-Partner-Harness-v0.3.9-logic\evidence\batch-2026-09-10\tools
$env:PYTHONPATH=(Get-Location).Path
& 'E:\AI\HSR Partner Harness\.venv\Scripts\python.exe' run_a14_sleep.py
# 本机真实休眠 3 分钟后由 WakeToRun 计划任务唤醒；异常时手工唤醒并删除 S4-A14-Wake 任务
