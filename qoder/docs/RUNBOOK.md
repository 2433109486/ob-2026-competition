# 运行说明（从零到可体验）

本项目在 **Windows 11 + PowerShell 7** 上完成并验证；Linux/macOS 可用等价命令。
所有命令默认在 `qoder/` 目录执行。

## 0. 环境清单

| 组件 | 本机验证版本 | 端口 | 说明 |
| --- | --- | --- | --- |
| Python | 3.12.13 | — | 3.10 及以上；推荐 3.12 |
| seekdb | 1.4.0.0（Windows 原生） | 2881 | MySQL 协议，root / 空密码 |
| PowerContext | 1.4.1（SQLite 后端） | 8765 | HTTP API；SQLite 适合单机演示 |
| FastAPI / Uvicorn | 0.162 / 0.54 | 7860 | 本项目的 Web 服务 |
| PyMySQL | 1.2.0 | — | seekdb SQL 客户端 |
| 浏览器 | Edge / Chrome | — | 支持 ES Modules、CSS conic-gradient |

> 如果只想看“检索”而暂时没有 PowerContext，可设置 `POWERCONTEXT_ENABLED=false`；
> 页面会显示“记忆降级”，检索仍可用，但研究画像/进度/矩阵记忆不会写入。

## 1. 启动 seekdb

### 1.1 Windows 原生（本项目实际使用）

下载/解压 seekdb 1.4.0.0 后，在 PowerShell 中启动（把路径换成你的实际路径）：

```powershell
& 'D:\seekdb\seekdb.exe' `
  '--base-dir=D:/seekdb/data' '--port=2881' --nodaemon
```

保持窗口打开。不要删除 data 目录，否则会重新初始化。

验证：

```powershell
.\.venv\Scripts\python.exe -c "import pymysql; c=pymysql.connect(host='127.0.0.1',port=2881,user='root',password=''); print(c.cursor().execute('SELECT 1'))"
```

预期输出 `1`。

### 1.2 Docker（替代方式）

```bash
docker run -d --name seekdb -p 2881:2881 oceanbase/seekdb:latest
```

镜像 tag/参数以 seekdb 官方仓库为准。核心要求只有：**本机 2881 可连接、root 空密码**
（或在 `.env` 中改成你的账号密码）。

## 2. 启动 PowerContext

### 2.1 安装

```powershell
# 官方推荐 uv tool
uv tool install --force "powercontext[cli,server]==1.4.1"

# 如果没有 uv，也可以在独立 venv 中：
# python -m venv ..\pc-venv
# ..\pc-venv\Scripts\python.exe -m pip install "powercontext[cli,server]==1.4.1"
```

Windows 上 `jieba==0.42.1` 可能需要本地 wheel；Linux/macOS 直接安装即可。
如果安装遇到构建问题，可参考 PowerContext 官方安装文档。

### 2.2 配置

复制示例并改成**本机绝对路径**：

```powershell
Copy-Item .env.powercontext.example .env.powercontext
notepad .env.powercontext
```

至少保证：

```dotenv
POWERCONTEXT_HOME=D:/agent/sandbox/.powercontext
POWERCONTEXT_SERVER_HTTP_HOST=127.0.0.1
POWERCONTEXT_SERVER_HTTP_PORT=8765
POWERCONTEXT_SERVER_DATABASE_KIND=sqlite
POWERCONTEXT_SERVER_DATABASE_URL=sqlite+aiosqlite:///D:/agent/sandbox/.powercontext/powercontext.db
POWERCONTEXT_SERVER_ACCESS_MODE=disabled
```

> SQLite 路径必须是绝对路径；Windows 路径推荐正斜杠。

### 2.3 启动

```powershell
powercontext server run --env-file .env.powercontext
```

保持终端运行。验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health/live
# status: ok
```

> 本项目不启用鉴权，`POWERCONTEXT_SERVER_ACCESS_MODE=disabled`，仅用于本地演示。
> 不要把这个配置直接暴露到公网。

## 3. 启动研脉

### 3.1 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3.2 配置

```powershell
Copy-Item .env.example .env
```

默认值已经对应本文档的端口；如果账号/端口不同，修改：

```dotenv
SEEKDB_HOST=127.0.0.1
SEEKDB_PORT=2881
SEEKDB_USER=root
SEEKDB_PASSWORD=
SEEKDB_DATABASE=yanmai

POWERCONTEXT_URL=http://127.0.0.1:8765
POWERCONTEXT_ENABLED=true
APP_PORT=7860
```

### 3.3 初始化资料库与研究记忆

```powershell
.\.venv\Scripts\python.exe scripts\check_env.py
.\.venv\Scripts\python.exe scripts\init_db.py --reset
```

预期：

```text
seekdb: {"seeded": true, "papers": 10, "chunks": 34, ...}
powercontext: {"seeded": true, ...}
counts: {"papers": 10, "chunks": 34, "notes": 5, ...}
```

`--reset` 会删掉并重建 **yanmai** 数据库中的表；不会删除 PowerContext 的旧 Scope。
如果只想补数据、不重置，去掉 `--reset`。

### 3.4 启动 Web

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 7860
```

或：

```powershell
.\run.ps1
```

打开 <http://127.0.0.1:7860>。

## 4. 重置为干净演示

```powershell
# 1) 重建 seekdb 数据（会删除本地演示数据）
.\.venv\Scripts\python.exe scripts\init_db.py --reset

# 2) 清空当前演示 Scope 的调用日志并新建一个干净 Scope
.\.venv\Scripts\python.exe scripts\reset_demo_scope.py
```

PowerContext 的旧 Scope 仍留在服务端，不会影响新 Scope；`runtime/powercontext_scope.txt`
指向当前演示 Scope。

## 5. 自动验收

```powershell
# 服务已在 7860 运行
.\.venv\Scripts\python.exe scripts\acceptance.py
```

预期最后一行：

```text
PASS: 21 checks -> .../docs/evidence/acceptance.json
```

浏览器级交互（需要 Edge + Playwright Python，见 `scripts/e2e_ui.py` 顶部说明）：

```powershell
python scripts\e2e_ui.py
```

## 6. 常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| `Can't connect to MySQL server ... 2881` | seekdb 未启动或端口不同；先 `scripts/check_env.py` |
| `PowerContext 未就绪：... HTTP 422` | PowerContext 版本低于 1.4.1，或请求模型不匹配；使用本文锁定版本 |
| 页面右上角“记忆降级” | PowerContext 未启动；启动后刷新。检索仍可用 |
| `ModuleNotFoundError: pymysql` | 没有用项目 `.venv`；确认 `.venv\Scripts\python.exe` |
| 向量检索结果很少 | 资料库为空或筛选过严；运行 `init_db.py` 并清空筛选 |
| 中文乱码 | 终端用 UTF-8；服务端 JSON 已按 UTF-8 输出，浏览器正常 |
| 端口 7860 被占用 | `--port 7861`，或修改 `.env` 的 `APP_PORT` |
| PowerContext 首次启动迁移失败 | 把 `TMP`/`TEMP` 指向工作区可写目录；Windows 上建议使用项目内 `runtime/tmp` |

## 7. 目录与端口速查

```text
seekdb       127.0.0.1:2881   root / (空)
PowerContext 127.0.0.1:8765   access mode disabled
研脉 Web     127.0.0.1:7860
```

数据库：`yanmai`；核心表：`papers`、`chunks`、`notes`、`search_log`、`activity`。
PowerContext Scope 文件：`runtime/powercontext_scope.txt`（已被 `.gitignore` 排除）。
