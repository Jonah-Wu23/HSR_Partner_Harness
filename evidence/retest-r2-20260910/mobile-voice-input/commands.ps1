# 本用例的原样复现命令（PowerShell / Git Bash 均可）

# 电脑扬声器朗读一句中文，同时手机端按住「语音」按钮 8 秒
cd E:\AI\HSR-Partner-Harness-v0.3.9-logic\evidence\retest-r2-20260910\tools
$env:PYTHONPATH=(Get-Location).Path
& 'E:\AI\HSR-Partner-Harness-v0.3.9-logic\.venv\Scripts\python.exe' run_mobile_asr.py
