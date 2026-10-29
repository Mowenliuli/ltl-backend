# ltl-backend（FastAPI + WebSocket + PostgreSQL）

## 技术栈

- **FastAPI**：Web 框架（REST API + WebSocket）
- **SQLAlchemy + psycopg2**：PostgreSQL 数据库访问
- **python-jose + passlib[bcrypt]**：JWT 认证、密码哈希
- **python-multipart**：文件上传

## 目录结构

```
ltl-backend/
├── main.py            # 应用入口、CORS、路由挂载
├── config.py          # 环境变量读取（支持 DATABASE_URL / MySQL / SQLite）
├── database.py        # SQLAlchemy 引擎与会话
├── models.py          # User / Conversation / Message / GroupMember 表
├── schemas.py         # Pydantic 请求/响应模型
├── auth.py            # 注册、登录、JWT 签发与校验、登录限流
├── ws.py              # WebSocket 连接管理与消息广播
├── routes/
│   ├── users.py       # 用户搜索
│   ├── chat.py        # 会话、历史消息、最近联系人
│   ├── groups.py      # 群聊管理（创建/改名/加人/踢人/退群/解散）
│   └── files.py       # 上传、鉴权下载
├── uploads/           # 图片/语音/文件存储（本地磁盘）
├── init_db.py         # 建表脚本（自动识别 PG/MySQL/SQLite）
├── requirements.txt
├── .env               # 本地开发环境变量（不提交 git）
└── .env.production    # 生产环境变量模板（不提交 git）
```

## 本地开发

### 1. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，填入本地 MySQL 配置：

```ini
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=123456
MYSQL_DB=ltl_chat
JWT_SECRET=local-dev-secret-not-for-production
JWT_EXPIRE_MINUTES=525600
```

### 3. 初始化数据库

```bash
python init_db.py
```

### 4. 启动服务

```bash
uvicorn main:app --reload --port 8000
```

访问 http://localhost:8000/docs 查看 API 文档。

---

## 部署到 Render

### 1. 创建 PostgreSQL 数据库

1. https://render.com → **New +** → **PostgreSQL**
2. 填写：
   - **Name**：`ltl-chat-db`
   - **Database**：`ltl_chat`
   - **User**：`ltl`
   - **Region**：`Singapore`（离国内最近）
   - **Plan**：**Free**
3. 点 **Create Database**
4. 创建完成后进入详情页，找到 **Connections** 区块，复制 **Internal Database URL**（形如 `postgresql://ltl:<密码>@<内部主机>/ltl_chat`）

### 2. 创建 Web Service

1. Render 控制台 → **New +** → **Web Service**
2. 选 **Build and deploy from a Git repository** → 连接你的 GitHub 仓库
3. 填写配置：

   | 字段 | 值 |
   | --- | --- |
   | **Name** | `ltl-chat-backend`（会变成 `https://ltl-chat-backend.onrender.com`） |
   | **Region** | `Singapore`（和数据库同一个区域） |
   | **Branch** | `main` |
   | **Root Directory** | 留空（仓库根目录就是后端代码） |
   | **Runtime** | **Python 3** |
   | **Build Command** | `pip install -r requirements.txt` |
   | **Start Command** | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
   | **Plan** | **Free** |

4. **不要急着点 Create**，先配置环境变量（下一步）

### 3. 配置环境变量

在 Web Service 创建页面往下滑，找到 **Environment Variables**，逐个添加：

| Key | Value | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | 第 1 步复制的 **Internal Database URL** | Render 会自动把 `postgres://` 转成 `postgresql+psycopg2://` |
| `JWT_SECRET` | 本地生成：`python -c "import secrets; print(secrets.token_hex(32))"` | 生产环境必填 |
| `APP_ENV` | `production` | 告诉后端读生产配置 |
| `UPLOAD_DIR` | `/opt/render/project/src/uploads` | Render 持久化磁盘路径 |
| `MAX_UPLOAD_MB` | `5` | 上传文件大小限制 |

> **注意**：`DATABASE_URL` 一定要填 **Internal Database URL**（内网地址），不要填 External（外网地址），否则每次查询都要走公网，慢且有流量费。

填完后点 **Create Web Service**，Render 会自动开始构建部署。

### 4. 初始化数据库表

部署完成后：

1. 进入 Web Service 详情页 → 左侧 **Shell** 标签
2. 在 Shell 里执行：

   ```bash
   python init_db.py
   ```

3. 看到 `数据库表已创建` 即成功

### 5. 验证部署

浏览器访问 `https://ltl-chat-backend.onrender.com/api/health`，应返回 `{"status": "ok"}`。

### 6. 数据库续期（重要）

Render 免费 PostgreSQL **90 天到期**，到期前会发邮件提醒。

续期方法：
1. 收到邮件后，进入数据库详情页
2. 点 **Settings** → **Delete Protection** 旁边的 **Extend Expiration** 按钮
3. 续期 90 天

> 如果忘了续期，数据库会被删除，数据丢失。建议设个日历提醒。

### 7. 常见问题

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| 部署失败 | `requirements.txt` 缺依赖 | 检查是否包含 `psycopg2-binary` |
| 502 Bad Gateway | 服务启动失败 | 看 **Logs** 标签页的错误信息 |
| WS 连不上 | `DATABASE_URL` 填成了 External | 改成 Internal Database URL |
| 首次访问慢 | 服务休眠唤醒 | 正常现象，等 30 秒 |
| 数据库连不上 | 密码错误 | 去数据库详情页 **Connections** 复制正确的 URL |

---

## 完整环境变量参考

**Render Web Service 环境变量**：

```ini
DATABASE_URL=postgresql://ltl:<密码>@<内部主机>/ltl_chat
JWT_SECRET=<64位十六进制>
APP_ENV=production
UPLOAD_DIR=/opt/render/project/src/uploads
MAX_UPLOAD_MB=5
```

**本地开发 `.env`**：

```ini
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=123456
MYSQL_DB=ltl_chat
JWT_SECRET=local-dev-secret-not-for-production
JWT_EXPIRE_MINUTES=525600
```

---

## 自动部署

GitHub 集成已经默认开启：每次 `git push` 到主分支，Render 会自动拉代码、构建、重启服务。

如果想关闭自动部署：
- Web Service 详情页 → **Settings** → **Build & Deploy** → **Auto-Deploy** 改成 **No**。
