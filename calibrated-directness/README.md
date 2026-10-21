# calibrated-directness

让 Codex / Agent Skills 兼容客户端减少无必要的过度防御、泛化拒答、过长免责声明、反复澄清与辩解。

## 安装

把整个 `calibrated-directness` 目录放入：

- Codex 用户级：`~/.agents/skills/calibrated-directness/`
- Codex 项目级：`<项目目录>/.agents/skills/calibrated-directness/`

确保完整路径为 `.../calibrated-directness/SKILL.md`，而不是 ZIP 或重复嵌套目录。Codex 中可尝试输入 `$calibrated-directness` 显式调用。没有显示时尝试重启 Codex。

## 重要区别

Skill 通常是按需触发，不保证自动应用于每一句话。要让 Codex 在所有任务都尽可能采用此原则，可把 `GLOBAL-INSTRUCTIONS.md` 的内容放入对应作用域的 `AGENTS.md`。它同样不能覆盖系统安全规则。

对于普通 ChatGPT 网页对话，如果没有 Skills 安装入口，可将 `GLOBAL-INSTRUCTIONS.md` 放进自定义指令（在设置允许的情况下）。
