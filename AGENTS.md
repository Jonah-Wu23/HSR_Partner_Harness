# Repository Guidelines

## 协作方式

默认使用简体中文。修改以当前需求为准，先完成主路径，再处理必要的测试和文档。

仓库中可能存在用户自己的本地文件。提交时写明文件路径，避免使用 `git add -A`。原始资料和旧版文件保存在 `.archive/`，该目录受 Git 忽略。

## 当前架构

桌面端位于 `desktop/`，界面使用 Tauri 2 和 React。Rust 负责启动 Python Sidecar，也负责桌面文件夹选择。

Python 包位于 `src/pair_harness/`。Sidecar 入口是 `pair_harness.desktop_backend`，业务状态以 Python 层为准。桌面端通过 JSONL 请求和事件与 Sidecar 通信。

桌面界面统一放在 `desktop/`。Python 包保留 Sidecar 所需的业务代码。

## 产品边界

角色负责对话，也可以形成结构化委派。文件操作和命令执行由助手完成。

消息必须保留来源字段。角色、助手使用各自身份，工具事件继续保持结构化展示。

语音功能使用 DashScope。自然语言回复可以朗读，工具记录保持静音。

项目绑定本地文件夹。新项目默认采用文件夹名称，用户可以随时改名。聊天初始名称为“新聊天”，首次完整回复结束后由助手生成标题；用户手动改名后，自动标题不得覆盖它。

## 常用命令

Python 测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

前端测试和构建：

```powershell
Set-Location desktop
npm test -- --run
npm run typecheck
npm run build
```

Rust 测试：

```powershell
Set-Location desktop\src-tauri
cargo test
```

NSIS 安装包：

```powershell
Set-Location desktop
npm run build:sidecar
npm run tauri -- build --bundles nsis
```

## 外部代码

`src/pair_harness/config/providers.py` 含有根据 DeepSeek-Reasonix 改写的供应商识别逻辑。修改这部分时保留文件内出处，并同步检查 `THIRD_PARTY_NOTICES.md`。

Codex 通过本机 app-server 接入，仓库不包含 Codex 源码。相关协议改动应以 OpenAI Codex 当前实现为准。
