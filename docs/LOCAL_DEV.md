# 本地开发环境与端口配置记录

> 最后更新：2026-10-19
> 适用仓库：`xianyu-auto-reply`（dev 分支）

## 1. Compose 项目组

所有服务统一归入一个 Compose 项目：

```text
项目名：xianyu-auto-reply
基础文件：docker-compose.yml
开发 override：docker-compose.dev.yml
共享网络：xianyu-network
```

- 主 compose 已包含 6 个服务：`mysql`、`redis`、`backend-web`、`websocket`、`scheduler`、`frontend`
- `docker-compose.dev.yml` 不再单独建项目，只作为 override：
  - 给 MySQL/Redis 增加宿主机端口映射（3307/6380）
  - 使用独立 dev 数据卷，避免和全量 Docker 数据混用
- 不要再单独执行 `docker compose -f docker-compose.dev.yml up`，它必须和主文件一起用。

## 2. 启动模式

| 模式 | 启动内容 | 宿主机端口 | 适用场景 |
|---|---|---|---|
| 宿主机源码开发（推荐） | MySQL/Redis 在 Docker，Python/前端在宿主机 | 3307、6380、8089、18090、8091、9000 | 日常二开、断点调试 |
| 全量 Docker | 6 个服务全部进容器 | 8089、18090、8091、9000 | 验证部署/联调 |
| 仅后端 | MySQL/Redis + backend-web | 3307、6380、8089 | 只调 API |

### 2.1 宿主机源码开发

```bash
# 只启动基础设施
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d mysql redis

# 先 backend-web（首次会建表、生成内部 token）
cd backend-web && ../.venv/bin/python main.py

# 可选：消息/登录
cd websocket && ../.venv/bin/python main.py

# 可选：定时任务
cd scheduler && ../.venv/bin/python main.py

# 前端
cd frontend && npm run dev
```

访问 `http://127.0.0.1:9000`，默认账号 `admin / admin123`。

### 2.2 全量 Docker

本机 8090 被 nginx 占用，所以必须显式指定 `WEBSOCKET_PORT=18090`：

```bash
WEBSOCKET_PORT=18090 \
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

如果 9000 已被宿主机 Vite 占用，再加 `FRONTEND_PORT=9001`。

### 2.3 停止与清理

```bash
# 停止，保留数据
docker compose -f docker-compose.yml -f docker-compose.dev.yml down

# 停止并清空 dev 数据（mysql_dev_data / redis_dev_data）
docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v
```

## 3. 服务清单

| 服务 | 容器名 | 镜像/构建 | 容器内端口 | 宿主机端口 | 数据卷 | 依赖 |
|---|---|---|---:|---|---|---|
| MySQL | `xianyu-mysql` | 阿里云 `xianyu-mysql:8.0` | 3306 | 默认不映射；dev override 3307 | `mysql_data` / dev `mysql_dev_data` | - |
| Redis | `xianyu-redis` | 阿里云 `xianyu-redis:7-alpine` | 6379 | 默认不映射；dev override 6380 | `redis_data` / dev `redis_dev_data` | - |
| backend-web | `xianyu-backend-web` | `backend-web/Dockerfile` | 8089 | 8089 | `backend_web_logs`、`static-files`、`backup-files` | mysql、redis |
| websocket | `xianyu-websocket` | `websocket/Dockerfile` | 8090 | 默认 8090；本机用 18090 | `websocket_logs`、`static-files`、`browser_data` | mysql、redis、backend-web |
| scheduler | `xianyu-scheduler` | `scheduler/Dockerfile` | 8091 | 8091 | `scheduler_logs`、`static-files`、`backup-files` | mysql、redis、websocket、backend-web |
| frontend | `xianyu-frontend` | `docker/frontend/Dockerfile` | 80 | 9000 | - | backend-web |

## 4. 端口记录

| 端口 | 用途 | 归属/模式 | 当前状态 | 备注 |
|---:|---|---|---|---|
| 3306 | MySQL 默认端口 | 宿主机/其它项目 | 空闲 | 本项目 Docker 不映射 |
| 3307 | dev MySQL | dev override | 本项目保留 | 宿主机 Python 服务连接 |
| 6379 | Redis 默认端口 | 其它项目（ottermind） | 已占用 | 不要使用 |
| 6380 | dev Redis | dev override | 本项目保留 | 宿主机 Python 服务连接 |
| 8089 | backend-web | 主 compose / 宿主机 | 空闲 | API 与 `/docs` |
| 8090 | nginx | 其它项目 | 已占用 | 全量 Docker 必须改 `WEBSOCKET_PORT=18090` |
| 18090 | websocket（宿主机 dev） | 宿主机 | 空闲 | `.env.dev` 中的 `WEBSOCKET_PORT` |
| 8091 | scheduler | 主 compose / 宿主机 | 空闲 | 健康检查 `/health` |
| 9000 | frontend / Vite | 主 compose / 宿主机 | 空闲 | 容器与 Vite 二选一 |
| 8092 | promotion 后端 | 可选 | 空闲 | 返佣子系统 |
| 9001 | promotion 前端 | 可选 | 空闲 | 返佣子系统 |
| 8081 / 19000 | xianyu-mobile Expo | 可选 | 空闲 | 移动端开发 |

## 5. 配置文件清单

| 文件 | 作用 | 是否入库 |
|---|---|---|
| `docker-compose.yml` | 全量服务定义、网络、卷 | 是 |
| `docker-compose.dev.yml` | dev override：MySQL/Redis 端口 + dev 卷 | 是 |
| `backend-web/.env.dev` | backend-web 本地模板 | 是 |
| `backend-web/.env` | backend-web 实际本地配置 | 否（gitignored） |
| `websocket/.env.dev` / `.env` | 同上 | 模板入库，实际文件不入库 |
| `scheduler/.env.dev` / `.env` | 同上 | 模板入库，实际文件不入库 |
| `.venv/` | Python 3.12 虚拟环境 | 否 |
| `frontend/node_modules/` | 前端依赖 | 否 |
| `docs/LOCAL_DEV.md` | 本文档 | 是 |

当前 dev 账号密码（与 `docker-compose.yml` 默认值一致）：

```text
MySQL: host=127.0.0.1 port=3307 user=xianyu password=xianyu@2026 database=xianyu_data
Redis: host=127.0.0.1 port=6380 password=xianyu@2026 db=0
```

## 6. 资源预算（本机实测）

| 项目 | 实测/估算 |
|---|---:|
| CPU | 10 核 |
| 内存 | 32GB（Docker Desktop 分配 7.75GB） |
| 可用磁盘 | 约 16GB（97% 已用） |
| 全服务空闲内存 | 约 1.29GB |
| 其中 backend-web | 204.5MB |
| 其中 websocket | 133.8MB |
| 其中 scheduler | 139.8MB |
| 其中 frontend Vite + esbuild | 374.1MB |
| 其中 MySQL | 426.8MB |
| 其中 Redis | 9.8MB |
| 仓库 + `.venv` + `node_modules` | 约 1.1GB |
| Docker 镜像 + dev 卷 | 约 1.4GB |
| Playwright 浏览器缓存 | 约 554MB |

结论：

- CPU/内存充足，跑全量服务没问题。
- **磁盘是瓶颈**：16GB 可用、97% 已用。做全量 Docker 构建前建议先清理 Docker 缓存，至少留 10GB。
- 浏览器自动化（扫码/滑块）每个 Chromium 再加 200-500MB；dev 已把 `MAX_CAPTCHA_CONCURRENT=1`。

## 7. 变更规则（重要）

1. **改端口**：同时改 `docker-compose.yml` / `docker-compose.dev.yml` 的环境变量、对应服务的 `.env.dev`，并更新本文档。不要只改一边。
2. **改数据库/Redis 密码**：同时改 `docker-compose.yml` 默认值、三个服务的 `.env.dev`，以及本地 `.env`；否则服务连不上。
3. **保持一个 Compose 项目**：项目名固定 `xianyu-auto-reply`，不要再创建第二个项目。
4. **dev 与全量 Docker 不要同时跑同一批端口**：两者二选一。
5. **dev 数据卷**：`mysql_dev_data`、`redis_dev_data` 只给本地开发；全量 Docker 使用 `mysql_data`、`redis_data`。
6. **旧项目清理**：之前独立 `xianyu-dev` 项目留下的卷已不再使用，确认不需要后可以删：

```bash
docker volume ls | grep xianyu-dev
docker volume rm xianyu-dev_xianyu_dev_mysql xianyu-dev_xianyu_dev_redis
```

7. **Docker 缓存清理**（磁盘紧张时）：

```bash
docker system df
docker builder prune
# 谨慎：会删除所有未使用镜像，包括其它项目的
# docker image prune -a
```

## 8. 已知限制

- 闲鱼网页端不展示拍卖出价按钮，出价必须在闲鱼 App 人工完成。
- 匿名详情接口可用，但连续调用会触发 `RGV587` 限流；自动搜索/高频刷新需要登录账号 + 代理池。
- 8090 被本机 nginx 占用；全量 Docker 启动 websocket 时必须 `WEBSOCKET_PORT=18090`。
- 6379 被 ottermind 的 Redis 占用；本项目 dev 固定用 6380。
