# 黑客松 OAuth 接入

适用范围：知乎黑客松参赛作品。

黑客松项目优先按本文接入。授权页面、回调参数和 Token 交换协议复用 [知乎 OAuth 应用集成](oauth.md)；App ID 和 App Key 通过赛事页面获取，无需走通用邮件申请流程。

获取授权用户基础信息使用独立接口 `https://openapi.zhihu.com/user`，详见 [获取授权用户基础信息](hackathon-user-profile-api.md)。创作列表与摘要、关注和收藏使用 [知乎开放平台用户数据 API](user-api.md)。

## 凭证与接口

| 能力 | 接口 | 鉴权 |
|---|---|---|
| 知乎登录后的基础信息 | `GET https://openapi.zhihu.com/user` | `Authorization: Bearer <OAuth access_token>` |
| 授权用户的创作列表与摘要、关注、收藏 | `https://developer.zhihu.com/api/v1/user/...`，仅限用户数据 API 文档的列表接口 | `Authorization: Bearer <Access Secret>`、`X-OAuth-Token: <OAuth access_token>`、`X-Request-Timestamp: <Unix 秒级时间戳>` |

只做知乎登录和获取基础信息，不需要 Access Secret。读取授权用户的创作列表、关注或收藏时，需要同时配置 Access Secret。CLI 日常查询仅使用 Access Secret 所属账号，不发起 OAuth，也不接收用户 OAuth Token。

本人全文、评论、账号统计和单篇统计四项接口只支持当前 Access Secret 所属账号，不能通过增加 `X-OAuth-Token` 切换身份，详见 [创作能力](creator.md)。活动故事和知识接口独立于登录，无需上述凭证，详见 [活动内容 API](hackathon-content-api.md)。

项目创建后，赛事页面分配 App ID 和 App Key。App ID 标识应用，App Key 用于后端换取 Token，均不同于开放平台 Access Secret。

凭证领取时机仍需核实：活动补充资料将“创建项目”放在作品提交入口开放后，未说明开发期间提前领取 App ID 和 App Key 的方式。实际接入先查看赛事页面已有凭证入口；尚无凭证时，可以完成代码、配置模板和 Mock 测试，再通过活动说明或官方答疑确认领取方式。不要编造提前领取入口，也不直接套用通用应用的邮件申请流程。

配置变量示例；已有项目沿用现有命名：

```text
ZHIHU_OAUTH_APP_ID
ZHIHU_OAUTH_APP_KEY
ZHIHU_OAUTH_REDIRECT_URI
ZHIHU_ACCESS_SECRET
```

App Key、Access Secret 和 OAuth Token 保存在后端安全凭证库、部署平台 Secret 或受控服务端存储中，不进入源码、URL、日志、前端响应或 Agent 输出。App ID 可作为公开配置。

## 回调与授权

优先复用项目已有的登记配置。回调地址缺失、存在多个候选或配置与赛事页面不一致时，请用户确认；确认前可以完成代码和配置模板。

实际授权联调前，核对 `redirect_uri` 的协议、域名、端口、路径、尾部斜杠和固定 Query 参数与赛事页面登记值完全一致。构造授权 URL 和交换 Token 使用同一地址，应用路由能够接收该地址的回调。

用户亲自完成知乎登录和授权页的最终确认。请求关联校验和协议待确认项遵循通用 OAuth 文档；核对回调地址不能替代 `state` 校验。

## 应用会话

复用作品已有后端、Serverless Function、云函数或框架服务端路由。纯浏览器项目增加最小后端，负责 Token 交换、用户信息请求和会话管理。

浏览器仅持有应用自己的随机会话标识，使用 `HttpOnly`、`Secure` Cookie 承载；OAuth Token 留在服务端。已有 Session、数据库或缓存时直接复用。常驻单进程 Demo 可用进程内 Map 保存会话标识、OAuth Token、过期时间和用户身份；多实例或 Serverless 使用共享会话存储。

用户退出或会话失效时清理映射；Token 过期或鉴权失败时停止读取，不切换到 Access Secret 所属账号。用户再次主动登录或使用需要授权的功能时，再发起授权，不在退出后自动重新登录。

## 交付验证

- 通过公网 HTTPS 回调地址完成实际授权，并读取当前授权用户的信息。
- 验证退出、会话失效和 Token 失效后的处理，确认浏览器及演示材料不包含完整密钥或 OAuth Token。
- 自动化测试使用 Mock；实际授权由开发者本人完成，Mock 通过不代表线上联调通过。
