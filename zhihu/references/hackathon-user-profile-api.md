# 获取授权用户基础信息

## 接口说明

本文依据黑客松补充资料整理，适用于黑客松参赛应用；其他应用的接口可用性与字段权限需按平台确认结果处理。

通过独立接口 `https://openapi.zhihu.com/user` 获取当前授权用户的标识、昵称、头像和个人介绍等。OAuth 接入见 [黑客松 OAuth 接入](hackathon-oauth.md)。

敏感字段 `email` 和 `phone_no` 只有在应用具备相应权限且用户完成授权时才会返回实际内容，否则返回空字符串。

## 接口信息

| 说明 | 值 |
|---|---|
| HTTP URL | `https://openapi.zhihu.com/user` |
| HTTP Method | `GET` |

## 请求头

| Header | 必填 | 说明 |
|---|---:|---|
| `Authorization` | 是 | OAuth 访问令牌，格式为 `Bearer <access_token>` |

请求示例：

```http
GET /user HTTP/1.1
Host: openapi.zhihu.com
Authorization: Bearer <access_token>
```

该接口的 `Authorization` 携带 OAuth 流程换取的用户 `access_token`；无需 Access Secret、`X-OAuth-Token` 或开放平台请求时间戳。

## 请求参数

无 Query 参数或请求体参数。

## 响应数据

### 成功响应示例

```json
{
  "uid": 969570047710216200,
  "hash_id": "0e4f7a...",
  "fullname": "用户昵称",
  "gender": "male",
  "headline": "一句话介绍",
  "description": "个人详细描述",
  "avatar_path": "https://picx.zhimg.com/example.jpg",
  "url": "https://openapi.zhihu.com/users/969570047710216200",
  "email": "",
  "phone_no": "",
  "phone": ""
}
```

### 响应字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `uid` | int64 | 知乎用户数字 ID，可能超过 JavaScript 安全整数范围，需无损解析 |
| `hash_id` | string | 用户字符串标识 |
| `fullname` | string | 用户昵称 |
| `gender` | string | 用户性别，可能为 `male`、`female` 或 `unknown` |
| `headline` | string | 用户的一句话介绍 |
| `description` | string | 用户的个人详细描述 |
| `avatar_path` | string | 用户头像 URL |
| `url` | string | 用户对应的 OpenAPI 访问地址 |
| `email` | string | 用户邮箱；应用无权限或用户未授权时为空字符串 |
| `phone_no` | string | 用户手机号；应用无权限或用户未授权时为空字符串 |
| `phone` | string | 手机号兼容字段；读取手机号优先使用 `phone_no` |

客户端兼容字段缺失、空值及额外扩展字段，不将示例视为所有应用均必返的字段集合。

JavaScript 前后端均须在 JSON 解析阶段无损处理 `uid`，再以字符串保存和传递；不能先解析成普通 Number 再转字符串，也不要据此将接口原始类型改写为 string。

## 响应处理

同时检查 HTTP 状态和响应内容，不能只凭 HTTP 200 判断成功。建立应用会话前，应确认响应包含有效用户标识。

通用 OAuth 文档记录的历史实测中，`code: 20000` 可表示成功，不能将所有非零 `code` 都视为失败。用户不存在的历史错误示例为 HTTP 200、`{"code":404,"data":"User don't exist"}`。鉴权失败时停止读取，不使用空对象建立登录会话。

## cURL 示例

```bash
curl -sS 'https://openapi.zhihu.com/user' \
  -H "Authorization: Bearer ${ZHIHU_OAUTH_ACCESS_TOKEN}"
```
