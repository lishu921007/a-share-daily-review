# 服务器部署说明

## 当前部署

- 项目目录：`/root/.openclaw/workspace/projects/a-share-daily-review`
- 前端公网端口：`18081`
- 后端本机端口：`127.0.0.1:18082`
- 公网访问：`http://43.156.201.98:18081`
- 后端健康检查：`http://127.0.0.1:18082/api/health`

## 服务管理

```bash
systemctl status a-share-daily-review-backend.service
systemctl status a-share-daily-review-frontend.service
systemctl restart a-share-daily-review-backend.service
systemctl restart a-share-daily-review-frontend.service
journalctl -u a-share-daily-review-backend.service -n 100 --no-pager
journalctl -u a-share-daily-review-frontend.service -n 100 --no-pager
```

## 边界说明

本次部署未修改 OpenClaw 网关、Nginx、`openclaw-gateway.service` 或大模型通道配置。

端口隔离：

- OpenClaw 当前监听：`127.0.0.1:18789`、`127.0.0.1:40483`
- 本项目监听：`0.0.0.0:18081`、`127.0.0.1:18082`

## 数据源配置

后端配置文件：

```text
backend/.env
```

当前没有写入 Tushare Token。需要真实拉取 A 股数据时，填写：

```env
TUSHARE_TOKEN=你的Token
DATA_SOURCE=tushare
LOCAL_DATA_MODE=false
```

修改后重启后端：

```bash
systemctl restart a-share-daily-review-backend.service
```

## 前端构建

```bash
cd /root/.openclaw/workspace/projects/a-share-daily-review/frontend
npm run build
systemctl restart a-share-daily-review-frontend.service
```
