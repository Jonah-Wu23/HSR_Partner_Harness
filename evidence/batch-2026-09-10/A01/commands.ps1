# A01 复现命令（并发/排队/取消）
cd E:\AI\HSR-Partner-Harness-v0.3.9-logic\evidenceatch-2026-09-10	ools
$env:PYTHONPATH=(Get-Location).Path
& 'E:\AI\HSR Partner Harness\.venv\Scripts\python.exe' run_a01.py
& 'E:\AI\HSR Partner Harness\.venv\Scripts\python.exe' run_a01_cancel.py
