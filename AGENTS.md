# Repository Guidelines

## 协作方式

默认使用简体中文。修改以当前需求为准，先完成主路径，再处理必要的测试和文档。

仓库中可能存在用户自己的本地文件。提交时写明文件路径，避免使用 `git add -A`。原始资料和旧版文件保存在 `.archive/`，该目录受 Git 忽略。

## 最高准则：Let It Fail, Let It Go

### Let It Fail

真实失败必须暴露，不能用兜底代码把失败改写成成功、空结果或伪造的失败回执。

- 诊断和真实联调时，不吞异常、不合成成功事件、不用默认文本掩盖未执行的任务。
- 需要验证真实链路时，使用真实配置、真实服务和真实 app-server；假模型、假 HTTP、Scripted/Fake engine 或 mock server 只能验证离线协议逻辑，不能作为真实链路通过的证据。
- 测试必须让错误直接失败。发现测试夹具与真实协议不一致时，更新夹具以匹配真实协议，不能为了让测试通过而放宽生产代码或增加未经证实的兼容分支。
- 修复只针对已观察到的根因；不得用关键词猜测、历史消息恢复或合成事件掩盖委派未触发、工具未执行或 app-server 已退出。
- 界面可以把底层异常转换为可读提示，但不得改变底层失败状态，也不得阻断原始错误继续进入日志和调用链。

### Let It Go

赋予大语言模型足够的权限，充分相信目前大语言模型的实力。

- 严禁在代码与脚本层面使用各种探针、正则与关键词检测限制大语言模型：意图判定（要不要委派、任务内容）、台词措辞、成败表述一律由模型自己负责，代码不得改写、补全或替换模型输出。
- 代码只做协议一致性检查（例如模型自报 delegate=true 却未返回 delegation 即协议违规，如实暴露）与安全边界（沙箱、审批），不做语义猜测。
- 用户的措辞千变万化，任何关键词词典、正则、句式模板都不可能覆盖；检测模型或用户文字意图的兜底一律视为缺陷，发现即删除。
- 角色卡与提示词只描述职责边界与输出协议，不维护关键词枚举式的意图判定清单。

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

首次运行状态重置是项目的刻意设计，不是误操作。每次打包 EXE 时都必须进行首次运行数据清理，由 `desktop/scripts/tauri-with-first-run-reset.ps1` 清空 `PairHarness` 本地数据目录以及 WebView 的 Local/Session Storage，使每次打包后的验证都回到新人第一次进入的状态；该清理是打包流程的必需步骤，不得省略。

NSIS 安装包：

```powershell
Set-Location desktop
npm run build:sidecar
npm run tauri -- build --bundles nsis
```

发布节奏：开发迭代只更新 `desktop/src-tauri/target/release/hsr-partner-harness.exe`，不重新生成或上传安装包。当前已经生成的安装包保持现状，下一次安装包更新安排在 v0.3.0。

## 外部代码

`src/pair_harness/config/providers.py` 含有根据 DeepSeek-Reasonix 改写的供应商识别逻辑。修改这部分时保留文件内出处，并同步检查 `THIRD_PARTY_NOTICES.md`。

Codex 通过本机 app-server 接入，仓库不包含 Codex 源码。相关协议改动应以 OpenAI Codex 当前实现为准。
