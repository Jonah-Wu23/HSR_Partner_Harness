"""生成 evidence/batch-2026-09-10/batch-manifest.json（§2 开测前检查）。"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(r"E:\AI\HSR-Partner-Harness-v0.3.9-logic")
EVIDENCE = REPO / "evidence" / "batch-2026-09-10"
RELEASE = REPO / "desktop" / "src-tauri" / "target" / "release"
EXE = RELEASE / "hsr-partner-harness.exe"
SIDECAR_DIR = RELEASE / "resources" / "sidecar" / "pair-harness-sidecar"
SIDECAR = SIDECAR_DIR / "pair-harness-sidecar.exe"
APK = (
    REPO
    / "desktop/src-tauri/gen/android/app/build/outputs/apk/arm64/debug/app-arm64-debug.apk"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_digest(root: Path) -> dict:
    """目录内全部文件的逐文件 SHA256 与聚合摘要（资源替换检查用）。"""
    files = {}
    if not root.exists():
        return {"root": str(root), "exists": False, "files": files, "digest": None}
    aggregate = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        file_hash = sha256(path)
        rel = str(path.relative_to(root)).replace("\\", "/")
        files[rel] = file_hash
        aggregate.update(rel.encode("utf-8"))
        aggregate.update(file_hash.encode("utf-8"))
    return {
        "root": str(root),
        "exists": True,
        "file_count": len(files),
        "files": files,
        "digest": aggregate.hexdigest(),
    }


def ps(command: str) -> str:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True, text=True, check=False,
    )
    return (out.stdout or "").strip()


def audio_devices() -> dict:
    raw = ps(
        "Get-CimInstance Win32_SoundDevice | Select-Object Name,Status,Manufacturer | ConvertTo-Json -Compress"
    )
    try:
        data = json.loads(raw) if raw else []
    except ValueError:
        data = raw
    if isinstance(data, dict):
        data = [data]
    endpoints = ps(
        "Get-PnpDevice -Class AudioEndpoint -Status OK | Select-Object FriendlyName | ConvertTo-Json -Compress"
    )
    try:
        endpoint_data = json.loads(endpoints) if endpoints else []
    except ValueError:
        endpoint_data = endpoints
    if isinstance(endpoint_data, dict):
        endpoint_data = [endpoint_data]
    return {"devices": data, "endpoints": endpoint_data}


def main() -> int:
    manifest = {
        "batch": "batch-2026-09-10",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "桌面/非移动专项；A05 与移动平台矩阵（A10/A11）不在本批次范围",
        "candidate": {
            "commit": "897193a2fb983cd39c8328e98f7e225963a1ee64",
            "branch": "feat/v0.3.9-logic",
            "contract": "contract-v1（5dae7017810fc893ccf0b3552e85994e077788f0 + "
                        "effa4f3144e57dd43b76ab5a5215980d767081c5）",
            "worktree": str(REPO),
        },
        "hashes": {
            "exe": {"path": str(EXE), "size": EXE.stat().st_size if EXE.exists() else None,
                    "sha256": sha256(EXE) if EXE.exists() else None},
            "sidecar_exe": {"path": str(SIDECAR),
                            "size": SIDECAR.stat().st_size if SIDECAR.exists() else None,
                            "sha256": sha256(SIDECAR) if SIDECAR.exists() else None},
            "desktop_dist": tree_digest(REPO / "desktop" / "dist"),
            "mobile_dist": tree_digest(RELEASE / "resources" / "mobile-dist"),
            "bundled_codex": tree_digest(RELEASE / "resources" / "codex"),
            "bundled_reasonix": tree_digest(RELEASE / "resources" / "reasonix"),
            "apk": {"path": str(APK), "exists": APK.exists(),
                    "sha256": sha256(APK) if APK.exists() else None},
            "fixtures": json.loads(
                (EVIDENCE / "fixtures" / "fixtures-manifest.json").read_text(encoding="utf-8")
            ),
        },
        "device": {
            "os": platform.system() + " " + platform.version(),
            "os_caption": ps("(Get-CimInstance Win32_OperatingSystem).Caption"),
            "os_build": ps("(Get-CimInstance Win32_OperatingSystem).BuildNumber"),
            "cpu": ps("(Get-CimInstance Win32_Processor).Name"),
            "memory_gb": round(
                int(ps("(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory") or 0)
                / (1024 ** 3),
                1,
            ),
            "display": ps(
                "Get-CimInstance Win32_VideoController | Select-Object -First 1 -ExpandProperty CurrentHorizontalResolution"
            )
            + "x"
            + ps(
                "Get-CimInstance Win32_VideoController | Select-Object -First 1 -ExpandProperty CurrentVerticalResolution"
            ),
            "scaling": "150%",
            "audio": audio_devices(),
        },
        "services": {
            "dialogue": {"provider": "deepseek", "base_url": "https://api.deepseek.com",
                         "model": "deepseek-v4-flash"},
            "coding_engine": {"configured": "deepseek（Reasonix/ACP）",
                              "bundled_codex_version": "0.147.0（EXE 内置，未用于本批次）"},
            "voice": {"provider": "DashScope", "asr_model": "qwen-audio-3.0-asr-flash-streaming",
                      "tts_model": "qwen-audio-3.0-tts-flash",
                      "base_url": "https://llm-lvsifcqt094yn1cm.cn-beijing.maas.aliyuncs.com/api/v1"},
            "secrets": "不记录密钥；对话与语音密钥分别存于账号 secret_refs",
        },
        "network": {
            "local_http": "sidecar --serve 0.0.0.0:8765（PWA 静态 + /ws）",
            "tailscale_https": "本批次未配置，未执行",
        },
        "config_identifiers": {
            "env_file": "%LOCALAPPDATA%\\PairHarness\\.env（真实模式入口，内容不记录）",
            "account": "验收账号（account_id 见 result.json 的 ids 字段）",
            "project": "project-alpha / project-beta（E:\\AI\\HSR-v039-acceptance）",
            "protocol_token": "WS 真实鉴权 token 由 remote.pair 换取；只记录 SHA256 前 16 位",
        },
        "upgrade_recovery_data": {
            "backup_path": "%APPDATA%\\com.jonahwu.hsr-partner-harness\\projects\\initial-project",
            "note": "升级恢复样本未单独构造；本批次未执行升级路径用例",
        },
        "evidence_root": str(EVIDENCE),
        "integrity_check": {
            "policy": "每次批次开始核对 exe/sidecar/dist 哈希；不一致立即停止并上报",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    path = EVIDENCE / "batch-manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("batch", "candidate", "device")},
                     ensure_ascii=False, indent=2))
    print("hashes written to", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
