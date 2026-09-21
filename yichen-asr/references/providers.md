# ASR 后端事实表

## Step ASR

- 执行脚本：环境变量 `YICHEN_STEP_ASR_SCRIPT` 指向的兼容执行器；也可安装为同级 `step-asr/scripts/step_asr_transcribe.py`
- 接口：`https://api.stepfun.ai/v1/audio/asr/sse`
- 默认模型：`stepaudio-2.5-asr`
- 凭证：`STEPFUN_API_KEY`、`STEP_API_KEY`，或现有 cc-switch 中的 Step 配置
- 优点：本地先分块；失败块可继续缩短重试；适合全文和内容分析
- 限制：当前执行器输出分块时间 Markdown，不是豆包 utterance 级原生 SRT

## 豆包 ASR（火山引擎）

- 执行脚本：`~/.agents/skills/yichen-volc-asr/scripts/transcribe.py`
- App ID：试用使用 `VOLC_ASR_TRIAL_APP_ID`，付费使用 `VOLC_ASR_PAID_APP_ID`；公开仓库不提供默认值
- 凭证：试用使用 `VOLC_ASR_TRIAL_TOKEN`，付费使用 `VOLC_ASR_PAID_TOKEN`；公开仓库不读取固定钥匙串项
- 接口：本地文件 base64 直传极速版，不再经过公开 TOS
- 优点：结构化全文、utterances、时间信息、SRT 和口播粗剪
- 防重复计费：同媒体先读取 `.asr_pending.json` 和 `.asr_cache.json`
- 财务限制：ASR Token 不能证明余额；需要登录费用中心，或由接口返回明确的欠费错误

## 火山引擎费用入口

- 账户概览：https://console.volcengine.com/finance/account-overview/
- 充值说明：https://www.volcengine.com/docs/3019/1176800?lang=zh
- 豆包语音文档：https://www.volcengine.com/docs/6561/109885?lang=zh

控制台中按“费用中心 → 账户概览 → 充值”操作。充值或购买资源包是外部付费行为，本 Skill 不自动执行。
