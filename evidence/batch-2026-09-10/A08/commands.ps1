# 本用例的原样复现命令（PowerShell / Git Bash 均可）

cd E:\AI\HSR-Partner-Harness-v0.3.9-logic\evidence\batch-2026-09-10\tools
$env:PYTHONPATH=(Get-Location).Path
& 'E:\AI\HSR Partner Harness\.venv\Scripts\python.exe' run_a08.py
# 语音输入源：Windows 系统 TTS 合成 16kHz 单声道 WAV（见同目录 a08-asr-input.wav）
