# tangyixiao-skills

个人 Codex skills 备份仓库。

## 同步范围

- 来源：`C:\Users\tangy\.codex\skills`
- 当前同步：所有包含顶层 `SKILL.md` 的用户 skill
- 排除：Codex 自带的 `.system`、嵌套 `.git`、常见缓存目录，以及 `.env`、私钥等运行时凭据
- 每次同步保留 skill 的脚本、参考资料、资源和许可证文件

## Codex 同步约定

当 Codex 获得、安装或更新 skill 时，由 Codex 在当前任务中读取本地 skill 树、完成差异检查，并使用 Git 将变更提交推送到 `origin/main`。本仓库不使用 PowerShell watcher、计划任务、登录启动项或后台常驻进程。

推送前必须排除 `.system` 和凭据文件，并核验实际的 `SKILL.md` 内容与仓库状态。
