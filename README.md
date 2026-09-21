# tangyixiao-skills

个人 Codex skills 备份仓库。

## 同步范围

- 来源：`C:\Users\tangy\.codex\skills`
- 当前同步：所有包含顶层 `SKILL.md` 的用户 skill
- 排除：Codex 自带的 `.system`、嵌套 `.git`、常见缓存目录，以及 `.env`、私钥等运行时凭据
- 每次同步保留 skill 的脚本、参考资料、资源和许可证文件

## 手动操作

在本仓库目录运行：

```powershell
.\sync-skills.ps1 -Push
```

只检查同步结果、不提交：

```powershell
.\sync-skills.ps1 -DryRun
```

## 默认同步

运行一次：

```powershell
.\install-skill-sync.ps1
```

它会创建当前 Windows 用户的登录时任务 `Tangyixiao Skills Sync`。今后安装或修改用户 skill 后，监视器会自动等待文件变更稳定，再提交并推送到 `origin/main`。

关闭自动同步：

```powershell
.\uninstall-skill-sync.ps1
```

自动同步使用当前 Git 凭据；如果远端发生冲突，任务会记录到 `%LOCALAPPDATA%\tangyixiao-skills\sync.log`，不会强制覆盖远端历史。
