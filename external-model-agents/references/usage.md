# 使用与运行限制

需要 Node.js >=22.19。执行入口为当前 skill 目录中的 `scripts/agent.mjs`，没有 npm 安装步骤。以下 `<skill-dir>` 替换成实际安装目录，PowerShell 用 `& node "<skill-dir>/scripts/agent.mjs" ...` 调用。

## 诊断和模型

```powershell
node "<skill-dir>/scripts/agent.mjs" doctor workbuddy
node "<skill-dir>/scripts/agent.mjs" doctor workbuddy-ai
node "<skill-dir>/scripts/agent.mjs" doctor zcode
node "<skill-dir>/scripts/agent.mjs" doctor opencode
node "<skill-dir>/scripts/agent.mjs" models opencode --refresh
node "<skill-dir>/scripts/agent.mjs" models workbuddy --refresh
```

`doctor` 默认只检查本地安装与凭据文件是否存在，不发送模型请求。`models --refresh` 是明确的模型元数据读取，可能联网或通过应用连接层读取登录；它不会发推理探测。模型出现在目录，不代表真实任务已验证。不要通过余额轮询或推理档位探测验证连接。

WorkBuddy 两版需要本机已经安装并登录对应应用，以及 DSH Desktop 中安装 `dsh-workbuddy-connect-community`。连接组件来自现有插件；不要求启动 DSH 桌面版，也不改其 profile。两版分别使用自己的登录与模型目录。OpenCode 是执行工具的运行时，因此 WorkBuddy 两路也需要它。无法自动找到应用时，可在当前进程设置 `WORKBUDDY_ELECTRON_BIN` 或 `WORKBUDDY_AI_ELECTRON_BIN` 为对应应用可执行文件路径。

OpenCode 使用现有 CLI；显式指定 `provider/model`。Zen 免费目录与已经配置的其他 provider 不是同一概念。免费标签和倍率只代表元数据记录时的声明，实际结算由来源决定。

ZCode 使用 `zcode-app-cli` 的 `app-server` 和会话级模型选择。安装包路径可通过单次调用的 `--config FILE` 指定，具体字段以本版本提供的诊断结果和示例配置为准。
当目录显示模型需要推理等级时，在任务 JSON 中增加 `"reasoningLevel": "low"` 等目录列出的准确等级；不要假设所有模型支持同一等级。该选项已通过模拟协议测试，仍须逐环境真实验证。

## 派出任务

先创建任务专用目录。修改已有 Git 项目时优先使用独立 worktree；执行器不会自动把 cwd 变成文件系统沙箱。

任务 JSON 通过 UTF-8 文件或 stdin 输入。示例中的模型必须换成模型目录中真实存在的 ID：

```json
{
  "provider": "opencode",
  "model": "opencode/CHOOSE_FROM_CURRENT_CATALOG",
  "prompt": "读取当前目录的 input.txt，将内容转为 ASCII 大写后写入 output.txt。只修改 output.txt。",
  "cwd": "D:/path/to/isolated-task",
  "mode": "workspace-write",
  "timeoutMs": 90000,
  "allowLive": true
}
```

```powershell
node "<skill-dir>/scripts/agent.mjs" --state-dir "D:/path/to/task-state" spawn --spec "D:/path/to/task.json"
node "<skill-dir>/scripts/agent.mjs" --state-dir "D:/path/to/task-state" status TASK_ID
node "<skill-dir>/scripts/agent.mjs" --state-dir "D:/path/to/task-state" wait TASK_ID --timeout-ms 30000
node "<skill-dir>/scripts/agent.mjs" --state-dir "D:/path/to/task-state" result TASK_ID
node "<skill-dir>/scripts/agent.mjs" --state-dir "D:/path/to/task-state" cancel TASK_ID
```

保存返回的 task ID，并对同一批任务始终使用同一绝对 `--state-dir`。省略时状态保存在当前目录 `.runtime/external-model-agents`；它不是全机器共享的并发锁。第一版只允许同一个 state-dir 同时运行一个任务，多个目录不能合用一个总额度承诺。

新任务需要显式 `allowLive:true`。续派也需要明确授权和剩余额度，通过帮助中列出的 followup 命令继续精确保存的原生会话。真实测试的一次性授权用完后，不得把该标志继续用于修复重试。

## 可执行的限制

- `read-only` 使用运行时的只读工具权限；不授权 shell 写入或嵌套代理。
- `workspace-write` 允许受配置限制的文件工具；第一版默认关闭任意 shell、外部目录访问和嵌套代理。因此主要覆盖读写文件与代码补丁，构建测试由当前 Codex 验收。
- `timeoutMs` 是本地执行超时；超时会中止本任务拥有的请求和进程。
- `maxTurns`、严格 token/积分预算和任意路径白名单若不能可靠强制执行，应在推理前拒绝；不能以提示词或估算假装硬限制。
- 原生运行时可能有内部网络重试。执行器不自动重派任务、不换模型、不切账号；这不等于承诺底层网络请求次数恒为一。
- 输出与事件有体积限制，敏感字段会脱敏。为保证任务输入不被截断或改写，任务状态目录的 `spec.json` 包含原始任务文本及配置：应把状态目录放在受保护的位置，不要在任务 JSON 中填入凭据，不要把它提交到 Git 或对外分享。完整原生应用会话仍可能存于应用自己的本地目录。

## 判断结果

`completed` 只表示运行时报告完成。Coding 验收仍须检查输出文件或 diff；`failed`、`timed_out`、`cancelled`、`interrupted` 与 `awaiting_input` 都不能写成完成。

权限请求需要人工决定时应交回主代理。取消只对该执行器创建的任务生效，不通过存储的任意 PID 终止应用。若旧 worker 仍存活或无法确认死亡，并发锁应保留；不要手动删锁来抢跑。

鉴权、积分、限流或目录不匹配时，先读脱敏错误和诊断。修复实现后也要遵守真实调用预算；不能擅自重测。不要修改桌面应用默认模型或已有 DSH 配置去绕过某个任务的失败。

## 接口来源

- [WorkBuddy Connect](https://github.com/corrinehu/dsh-workbuddy-connect)：现有 MIT 连接组件，由本地已安装包提供。
- [OpenCode CLI](https://opencode.ai/docs/cli/) 与 [权限配置](https://opencode.ai/docs/permissions/)：任务运行、会话和工具权限。
- [ZCode CLI](https://github.com/kingsword09/zcode-cli)：非官方 CLI，复用随 ZCode 提供的 Agent 运行时。协议兼容性以实际安装版本为准。
