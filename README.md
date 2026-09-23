# health-ingest

接收 [HC Webhook](https://github.com/mcnaveen/health-connect-webhook) 推送的 Health Connect 数据，落 SQLite，供 hermes 拉取分析。

## 数据流

```
华为手环 → 华为运动健康 → Health Sync → Health Connect（手机）
                                            │
                              HC Webhook（手机 App）
                                            │ HTTPS POST
                                            ▼
                                    本服务（服务器）
                                            │
                              hermes 拉取 → 每日分析
```

## 部署

### 1. 配置

```bash
cp config.example.yaml config.yaml
```

改 `ingest_key` 为随机串，确认 `listen` 端口与 `docker-compose.yml` 的端口映射一致。

### 2. 启动

```bash
docker compose up -d --build
```

### 3. 反向代理

Caddy：

```
health.example.com {
    reverse_proxy 127.0.0.1:38117
}
```

Nginx：

```
server {
    listen 443 ssl;
    server_name health.example.com;

    location / {
        proxy_pass http://127.0.0.1:38117;
    }
}
```

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/ingest` | 接收 HC Webhook 推送。需请求头 `x-api-key`，值等于配置里的 `ingest_key` |
| `GET` | `/export?days=N` | 导出最近 N 天的记录，按数据类型分组 |
| `GET` | `/ping` | 健康检查 |

## 手机端配置（HC Webhook）

1. Play 商店安装 **Health Connect to Webhook**
2. **Webhooks → 新增**：URL 填 `https://<你的域名>/ingest`
3. 自定义请求头：`x-api-key` = 你配置里的 `ingest_key`
4. **数据类目**勾选：睡眠、心率、心率变异性、血氧、呼吸频率、皮肤温度、步数、距离、活动卡路里、总卡路里
5. **Sync 模式**选 Scheduled，设一个早上的时间点（需早于 hermes 分析时间）

## hermes 拉取

```bash
curl "https://<你的域名>/export?days=7"
```

数据按类型分组，各字段定义见 HC Webhook 的 [docs/webhook.md](https://github.com/mcnaveen/health-connect-webhook/blob/main/docs/webhook.md)。

## 行为说明

- 写入按 `UNIQUE(type, ts, payload)` 去重，重复推送被忽略，接口幂等
- HC Webhook 默认按各类型的水位线**增量**推送；若超过 48 小时未能同步成功，超出窗口的数据会缺失
- 数据库文件位于 `./data/health.db`，直接 CP 走即可备份
- `ts` 取记录的时间字段（`time` → `start_time` → `session_end_time` 依次匹配），用于按天筛选
