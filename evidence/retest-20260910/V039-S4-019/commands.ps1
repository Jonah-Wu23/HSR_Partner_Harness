# 本用例的原样复现命令（PowerShell / Git Bash 均可）

# Sidecar 必须以 INFO 级启动，否则本用例的归因日志不可观测
$env:PAIR_HARNESS_LOG_LEVEL='INFO'
python evidence/retest-20260910/tools/run_019_attribution.py
