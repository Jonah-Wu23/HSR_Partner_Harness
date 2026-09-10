#!/usr/bin/env bash
# 手机端列表导航助手：按可见文本点击（先 dump 再按 bounds 中心点击），避免坐标漂移点错会话。
set -euo pipefail
export MSYS_NO_PATHCONV=1
ADB="E:/AI/CHD-class-table/tools/android-sdk/platform-tools/adb.exe"
export ANDROID_SERIAL=10.81.140.245:42919
PY="E:/AI/HSR-Partner-Harness-v0.3.9-logic/.venv/Scripts/python.exe"
TARGET="$1"
OUT="${2:-/tmp/ui-tap.xml}"

"$ADB" shell uiautomator dump /sdcard/ui-tap.xml >/dev/null 2>&1
"$ADB" shell cat /sdcard/ui-tap.xml > "$OUT" 2>/dev/null
COORDS=$("$PY" -c "
import re, html, sys
target = sys.argv[1]
x = open(sys.argv[2], encoding='utf-8', errors='replace').read()
for m in re.finditer(r'<node[^>]*>', x):
    g = m.group(0)
    t = re.search(r'text=\"([^\"]*)\"', g)
    b = re.search(r'bounds=\"\[(\d+),(\d+)\]\[(\d+),(\d+)\]\"', g)
    if not t or not b:
        continue
    if target in html.unescape(t.group(1)):
        cx = (int(b.group(1)) + int(b.group(3))) // 2
        cy = (int(b.group(2)) + int(b.group(4))) // 2
        print(cx, cy)
        break
" "$TARGET" "$OUT")
if [ -z "$COORDS" ]; then
  echo "NOT_FOUND: $TARGET"
  exit 3
fi
echo "TAP $TARGET at $COORDS"
"$ADB" shell input tap $COORDS
