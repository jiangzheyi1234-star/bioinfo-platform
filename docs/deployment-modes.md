# H2OMeta 部署模式

H2OMeta 支持三种部署模式，适用于不同的使用场景和安全需求。

> 当前支持并验收的运行方式是 Desktop 模式。Server Single-User 的
> Docker Compose 文件为实验性草案，尚未完成镜像构建、网络安全和远程浏览器
> API 访问验收，不应作为生产部署方案使用。
> 当前 Compose 草案会显式声明 `server-single-user` 和 `H2OMETA_API_HOST=0.0.0.0`，
> 因而会被部署安全验证拒绝；它保留为后续反向代理/容器网络硬化工作的输入，
> 不是可启动的生产 profile。
> `.github/container-runtime-hardening.target.json` 是当前 Compose 草案的
> 机器可审计毕业门槛；只要该政策仍声明 `unsupported-draft`，
> Compose 就不得被当作生产可用部署。
> `server-multi-user` 尚未实现；设置
> `H2OMETA_DEPLOYMENT_MODE=server-multi-user` 会在 Local API 启动时失败。
> 缺失、空白或非法的 `H2OMETA_DEPLOYMENT_MODE` 值同样会失败，不再回退到 Desktop。

## 部署模式对比

| 模式 | 认证 | 凭据存储 | 网络暴露 | 适用场景 |
|------|------|----------|----------|----------|
| `desktop` | 无 | OS Keyring | 仅 localhost | 单用户本地开发 |
| `server-single-user` | 后续反向代理/Token 目标 | 环境变量 | 当前仅允许 localhost；Compose 草案会被拒绝 | 单用户服务器部署草案 |
| `server-multi-user` | 完整认证 + RBAC | 加密数据库 | 可公网 | 规划中，当前不可选择 |

## Desktop 模式

**适用场景**：个人开发者在本地机器上使用 H2OMeta。

**特点**：
- 无需认证，单用户使用
- 凭据存储在操作系统 Keyring（Windows Credential Manager / macOS Keychain / Linux Secret Service）
- 仅绑定 `127.0.0.1`，不接受外部连接
- 通过 `run.bat --web` 或 `run.bat --desktop` 启动

**启动方式**：
```bash
# Windows
run.bat --web

# 或桌面应用
run.bat --desktop
```

## Server Single-User 模式

**适用场景**：后续单用户服务器部署草案；当前不是可验收的内网或公网部署方案。

**状态**：实验性草案，暂缓交付。以下内容是目标设计和后续验收说明，
不是当前生产部署承诺。

**特点**：
- 后续需要通过反向代理或等效边界添加认证；当前草案不得作为无认证服务器暴露
- 敏感信息通过环境变量传递（`H2OMETA_RUNNER_TOKEN` 等）
- API 只允许绑定 localhost；网络访问必须通过后续验收过的反向代理/认证层
- 使用 Docker Compose 部署
- 数据持久化到 Docker Volume

**安全警告**：
> ⚠️ 当前 `server-single-user` 草案不适用于内网或公网直接暴露。API 必须保持 localhost 绑定；任何 bind-all/外部访问 profile 都要先完成反向代理认证、容器网络阻断、密钥挂载和验收测试。

**目标草案验证步骤（完成反向代理/容器网络阻断修复后使用）**：

1. 复制环境变量模板：
```bash
cp .env.example .env
```

2. 编辑 `.env` 配置：
```bash
# 生成强随机令牌
openssl rand -hex 32

# 编辑 .env
H2OMETA_RUNNER_TOKEN=<生成的令牌>
H2OMETA_SSH_HOST=your-runner-host
H2OMETA_SSH_USER=your-user
```

3. 启动服务：
```bash
docker compose up -d
```

4. 访问：
- Web UI: http://localhost:3765
- API: http://localhost:8765

**反向代理配置示例（Nginx）**：
```nginx
server {
    listen 443 ssl http2;
    server_name h2ometa.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # 添加基础认证
    auth_basic "H2OMeta";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:3765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## Server Multi-User 模式

**适用场景**：多用户团队协作，需要完整的用户管理和权限控制。

**特点**：
- 完整的用户认证（用户名/密码、OAuth2）
- 基于角色的访问控制（RBAC）
- 租户隔离和审计日志
- 凭据加密存储在数据库
- 可安全暴露到公网

**状态**：🚧 **规划中**，尚未实现。

当前版本 fail closed：选择此模式会启动失败。只有在认证、RBAC、租户隔离、
secret vault、PostgreSQL、对象存储和组织级审计边界完成后，才允许启用。

**计划功能**：
- 用户注册和登录
- 角色和权限管理（Admin / Developer / Viewer）
- 项目和资源隔离
- 操作审计日志
- PostgreSQL 数据库
- 可选对象存储（S3/MinIO）

## 环境变量参考

### 通用变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `H2OMETA_DEPLOYMENT_MODE` | 部署模式；所有入口必须显式设置 | 必填 |
| `H2OMETA_DATA_ROOT` | 数据根目录 | `~/.h2ometa` |
| `H2OMETA_RUNTIME_BUILD_ID` | 构建标识 | `dev` |
| `H2OMETA_BACKEND_SOURCE` | 后端来源 | `unknown` |

### Server Single-User 变量

| 变量 | 说明 | 必需 |
|------|------|------|
| `H2OMETA_RUNNER_TOKEN` | Remote Runner API 令牌 | ✅ |
| `H2OMETA_SSH_HOST` | SSH 主机 | ✅ |
| `H2OMETA_SSH_PORT` | SSH 端口 | ❌ (22) |
| `H2OMETA_SSH_USER` | SSH 用户 | ✅ |
| `H2OMETA_SSH_AUTH_MODE` | 认证模式 | ❌ (password_ref) |
| `H2OMETA_REMOTE_RUN_WORKER` | 启用 Remote Worker | ❌ (1) |
| `H2OMETA_REMOTE_ENABLE_MULTI_SLOT` | 允许 Remote Worker 多槽启动 | ❌ (0) |
| `H2OMETA_REMOTE_RUN_WORKER_SLOTS` | Remote Worker slot 数；生产默认 1，P0-3B 仅在 `H2OMETA_REMOTE_ENABLE_MULTI_SLOT=1` 时允许 2 | ❌ (1) |
| `H2OMETA_REMOTE_RUN_WORKER_TOTAL_CPU` | Remote Worker workflow 级 CPU admission 总量 | ❌ (1) |
| `H2OMETA_REMOTE_RUN_WORKER_TOTAL_MEMORY_MB` | Remote Worker workflow 级内存 admission 总量 | ❌ (0) |
| `H2OMETA_REMOTE_RUN_WORKER_TOTAL_DISK_MB` | Remote Worker workflow 级临时磁盘 admission 总量 | ❌ (0) |
| `H2OMETA_REMOTE_RUN_WORKER_TOTAL_GPU` | Remote Worker workflow 级 GPU admission 总量 | ❌ (0) |

### Server Multi-User 变量（计划，当前不可启用）

| 变量 | 说明 | 当前状态 |
|------|------|----------|
| `H2OMETA_AUTH_SECRET` | JWT 签名密钥 | 计划必需，当前不可启用 |
| `H2OMETA_DATABASE_BACKEND` | 数据库后端；计划支持 PostgreSQL，当前仅允许 `sqlite` | 计划必需，当前非 `sqlite` 会被拒绝 |
| `H2OMETA_DATABASE_URL` | PostgreSQL 连接串 | 计划必需，当前设置会被启动校验显式拒绝 |
| `H2OMETA_S3_ENDPOINT` | S3/MinIO 端点 | 计划可选 |
| `H2OMETA_S3_BUCKET` | S3 存储桶 | 计划可选 |

当前 remote runner control-plane 数据库后端只支持 SQLite。配置 `database_backend`
为 `postgres` 或设置 `H2OMETA_DATABASE_URL`/`database_url` 会 fail closed，并返回
`REMOTE_RUNNER_DATABASE_BACKEND_UNSUPPORTED` 或 `REMOTE_RUNNER_DATABASE_URL_UNSUPPORTED`。
PostgreSQL 只能在 repository/transaction 边界、迁移策略和多用户治理验收完成后启用。

## 安全最佳实践

### Desktop 模式
- ✅ 保持默认 `127.0.0.1` 绑定
- ✅ 定期更新操作系统和依赖
- ✅ 使用强密码保护 OS Keyring

### Server Single-User 模式
- ✅ 将 API 绑定到 localhost，并通过反向代理添加认证
- ✅ 在后续验收 profile 中通过反向代理/防火墙只暴露认证入口，API 仍保持 localhost/container-internal 边界
- ✅ 定期轮换 `H2OMETA_RUNNER_TOKEN`
- ✅ 使用 HTTPS（通过反向代理）
- ❌ 不要直接绑定 `0.0.0.0`；当前安全验证会拒绝该配置
- ❌ 不要在 `.env` 文件中提交敏感信息到 Git

### Server Multi-User 模式
- ✅ 启用 HTTPS（Let's Encrypt 或自签证书）
- ✅ 配置强密码策略
- ✅ 启用审计日志
- ✅ 定期备份数据库
- ✅ 使用环境变量存储 `AUTH_SECRET`
- ❌ 不要硬编码密钥到代码

## 升级路径

```
desktop → server-single-user → server-multi-user
  ↓              ↓                    ↓
本地开发      后续服务器草案        生产环境
单用户        单用户，未验收        多用户
```

**从 Desktop 升级到 Server Single-User**：
1. 准备服务器环境（安装 Docker）
2. 配置 `.env` 文件
3. 运行 `docker compose up -d`
4. 配置反向代理（可选）

**从 Server Single-User 升级到 Server Multi-User**：
1. 等待 Multi-User 模式发布
2. 迁移数据到 PostgreSQL
3. 配置用户认证
4. 设置 RBAC 策略

## 故障排查

### Docker Compose 启动失败

```bash
# 查看日志
docker compose logs -f api
docker compose logs -f web

# 检查健康状态
docker compose ps
curl http://localhost:8765/health
```

### 无法连接 Remote Runner

```bash
# 检查 SSH 配置
docker compose exec api env | grep SSH

# 测试 SSH 连接（使用已信任的 known_hosts）
docker compose exec api ssh -o StrictHostKeyChecking=yes $H2OMETA_SSH_USER@$H2OMETA_SSH_HOST
```

### 数据持久化问题

```bash
# 查看 Volume 位置
docker volume inspect bio_ui_h2ometa-data

# 备份数据
docker run --rm -v bio_ui_h2ometa-data:/data -v $(pwd):/backup alpine tar czf /backup/data-backup.tar.gz /data

# 恢复数据
docker run --rm -v bio_ui_h2ometa-data:/data -v $(pwd):/backup alpine tar xzf /backup/data-backup.tar.gz -C /
```
