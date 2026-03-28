# Discord-Beanfun 專案文件

## 專案概述

Discord-Beanfun 是一個 Discord 機器人，允許多人在 Discord 頻道上共享同一個 Beanfun 登入器，目前僅支援新楓之谷 (TMS, 服務代碼 610074/T9)。

**核心流程：**
```
使用者 <-> Discord 伺服器 <-> Bot (aiohttp) <-> Beanfun 網站
```

---

## 目錄結構

```
discord-beanfun/
├── src/
│   ├── main.py                      # Bot 入口，載入 cogs、條件性啟動 HTTP API server
│   ├── cogs/
│   │   ├── beanfun_cogs.py          # Beanfun 斜線指令 (login, status, game, logout...)
│   │   └── api_cogs.py              # API Token 管理指令 (register-app, list-apps, revoke-app)
│   ├── methods/
│   │   └── beanfun.py               # BeanfunLogin 核心：QR 登入、心跳、OTP、帳號列表
│   ├── api/
│   │   └── server.py                # HTTP API server (aiohttp.web)，獨立於 cog
│   ├── database/
│   │   └── token_db.py              # SQLite token 管理 (aiosqlite)
│   ├── utils/
│   │   ├── config.py                # 環境變數讀取
│   │   ├── model.py                 # Pydantic 資料模型
│   │   └── util.py                  # SSL、JSON 擷取、DES 解密、隱藏訊息
│   └── exceptions/
│       └── beanfun_error.py         # LoginTimeOutError
├── pyproject.toml                   # 專案設定 (uv)
├── requirements.txt                 # Docker 用 pip 依賴
├── Dockerfile                       # python:3.10-slim-buster
├── .github/workflows/docker.yml     # CI: 推送 main → 建置多架構 Docker 映像
└── README.md
```

---

## 架構分層

### 1. main.py — 入口

- 建立 `commands.Bot`（前綴 `.`，`Intents.all()`）
- 啟動時自動載入 `cogs/` 下所有 `.py` 檔
- 提供 `.load` / `.unload` / `.reload` 前綴指令管理 cog

### 2. BeanfunCog (cogs/beanfun_cogs.py) — Discord 指令層

以 `interaction.channel_id` 為 key，管理每個頻道一個 `BeanfunLogin` 實例。

**斜線指令：**

| 指令 | 說明 |
|------|------|
| `/login` | 產生 QR Code，等待掃碼登入，成功後啟動心跳 |
| `/status` | 顯示心跳狀態、剩餘點數、帳號列表 |
| `/game` | 選擇帳號取得 OTP 密碼（自動補全帳號名稱） |
| `/set_logout_ttl` | 設定自動登出秒數 |
| `/logout` | 立即登出 |
| `/about` | 免責聲明與專案連結 |

**前綴指令：**

| 指令 | 說明 |
|------|------|
| `.sync` | 同步斜線指令到當前伺服器 |
| `.load` / `.unload` / `.reload` | 動態管理 cog |

### 3. BeanfunLogin (methods/beanfun.py) — Beanfun 通訊層

以 `aiohttp.ClientSession` 管理 HTTP 工作階段，實作完整的 Beanfun 登入流程。

**核心方法：**

| 方法 | 說明 |
|------|------|
| `get_login_info()` | 取得 QR 圖片 (base64) 與 DeepLink |
| `get_login_status()` | 檢查掃碼登入結果 (ResultCode=1 時完成登入) |
| `logout()` | 登出並重置所有狀態 |
| `get_heartbeat()` | 心跳維持登入，失效時自動登出 |
| `get_game_point()` | 取得剩餘點數 |
| `get_maplestory_account_list()` | 取得遊戲帳號列表 (快取) |
| `get_account_otp(account)` | 取得指定帳號的 OTP 動態密碼 |
| `heartbeat_loop(callback)` | 背景心跳迴圈 (每 60 秒) |
| `waiting_login_loop(callback)` | 等待 QR 掃碼迴圈 (最多 120 次) |
| `close_connection()` | 關閉 HTTP session |

**登入流程：**
1. `logout()` 清除先前狀態
2. GET `m.beanfun.com` → 取得 `skey`
3. GET `tw.newlogin.beanfun.com/checkin.aspx` → 建立工作階段
4. GET `login.beanfun.com/Login/Index` → 取 `__RequestVerificationToken`
5. GET `login.beanfun.com/Login/InitLogin` → 取 QR 圖片與 DeepLink
6. 輪詢 `CheckLoginStatus`，`ResultCode == 1` 時：
   - GET `QRLogin/QRLogin` → 取得 cookie
   - GET `Login/SendLogin` → 解析 AuthKey / SessionKey
   - POST `return.aspx` → 完成登入
   - 從 cookie 讀取 `bfWebToken`

**OTP 取得流程：**
1. GET `game_start_step2.aspx` → 解析 MyAccountData 與 polling key
2. POST `record_service_start.ashx` → 記錄服務啟動
3. GET `get_cookies.ashx` → 取得 SecretCode
4. GET `get_webstart_otp.ashx` → 取得加密 OTP
5. DES ECB + PKCS5 解密 → 明文密碼

### 4. 資料模型 (utils/model.py)

| 模型 | 欄位 |
|------|------|
| `LoginQRInfo` | QRImage, DeepLink, IsHK, IsRecaptcha, RecaptchaV2PublicKey, IsOTP |
| `CheckLoginStatus` | Result, ResultCode, ResultMessage |
| `HeartBeatResponse` | ResultCode, ResultDesc, MainAccountID |
| `GamePointResponse` | RemainPoint, ResultCode, ResultDesc |
| `MSAccountModel` | account_name, account, sn |
| `BeanfunAccountInfo` | account_hidden, point（目前未使用） |

### 5. 工具函式 (utils/util.py)

- `SSL_CTX` — 自訂 SSL 密碼套件（解決 tw.beanfun.com 連線問題）
- `extract_json(s, double_quotes)` — 從文字擷取 JSON 物件
- `decrypt_des_pkcs5_hex(text)` — DES ECB 解密 OTP
- `hidden_message(msg)` — 依設定包裹 Discord spoiler `||...||`

---

## 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `BOT_TOKEN` | 無 | Discord Bot Token（必填） |
| `LIMIT_GUILD` | `""` | 逗號分隔的 Guild ID 列表 |
| `LOGIN_TIME_OUT` | `180` | QR 掃碼逾時（秒） |
| `OTP_DISPLAY_TIME` | `20` | OTP 訊息顯示秒數 |
| `HIDDEN_PRIVATE_MESSAGE` | `1` | 1=使用 spoiler 隱藏敏感資訊 |
| `REDIRECT_URL` | `False` | 設定後會產生 DeepLink 跳轉 URL |
| `FEAT_APP_SERVER` | `0` | 功能總開關，設為 `1` 或 `True` 啟用 API Server |
| `API_PORT` | `8080` | HTTP API server 監聽 port |
| `DB_PATH` | `./data/tokens.db` | SQLite 資料庫檔案路徑 |

---

## 依賴

**執行時依賴：**
- `discord.py==2.3.1` — Discord API
- `aiohttp==3.8.4` — 非同步 HTTP（同時用於 Beanfun 通訊與 API server）
- `lxml==4.9.3` — HTML 解析
- `pycryptodome==3.18.0` — DES 解密
- `pydantic==2.0.2` — 資料驗證
- `aiosqlite>=0.19.0` — 非同步 SQLite（API Token 儲存）
- `qrcode==7.4.2` — QR Code（目前未使用）
- `requests==2.31.0` — HTTP（目前未使用）

**開發依賴：** `black`, `flake8`

---

## 部署

- **Docker 映像：** `takidog/discord_beanfun:latest`
- **基底映像：** `python:3.10-slim-buster`
- **架構：** linux/amd64, linux/arm64
- **CI：** 推送到 `main` 分支時自動建置並推送到 Docker Hub

---

## 狀態管理

- 登入狀態以 `channel_id` 為 key 存放在 `bot.login_dict` (記憶體內 dict，bot 層級共享)
- 每個頻道最多一個 `BeanfunLogin` 實例
- 登入狀態不持久化，Bot 重啟後需重新登入
- 心跳迴圈每 60 秒檢查一次
- 支援自動登出（`auto_logout_sec`）

---

## API Server 功能 (FEAT_APP_SERVER)

透過 `FEAT_APP_SERVER=1` 啟用。預設關閉，關閉時 Bot 行為與原始完全一致。

此功能主要是提供「地端輔助登入器」使用，讓你在自己的電腦或內網工具中，透過 token 安全地查詢登入狀態與取得 OTP，而不需要直接操作 Discord 指令流程。

### 架構原則

HTTP API Server 與 Discord Cog **完全解耦**，互不 import。兩者透過 `bot` 物件上的共享狀態溝通：
- `bot.login_dict` — 各頻道的 BeanfunLogin 實例
- `bot.token_db` — SQLite token 資料庫

### Discord 指令（api_cogs.py）

| 指令 | 說明 |
|------|------|
| `/register-app` | 透過 Modal + Select 互動式建立 API Token |
| `/list-apps` | 列出本頻道已註冊的應用程式 |
| `/revoke-app` | 撤銷自己建立的 Token |

### HTTP API 端點（api/server.py）

所有端點都需要通過兩層 header 檢查：

1. 必須攜帶 `Authorization: Bearer <token>`
2. 必須攜帶 `X-Beanfun-Guard: discord-beanfun`

若第 2 點不符合，伺服器會直接回 `401 Unauthorized`。

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/status` | 查詢 token 對應頻道的登入狀態 |
| GET | `/account` | 取得可用的遊戲帳號列表 |
| POST | `/account` | 取得指定帳號的 OTP 密碼（同時通知 Discord 頻道） |

**POST /account** 請求格式：
```json
{"account": "account_id"}
```

### Token 管理

- Token 使用 `secrets.token_urlsafe(32)` 產生
- 儲存於 SQLite（路徑由 `DB_PATH` 控制）
- 支援過期時間：永久、7天、30天、60天、90天
- 支援手動撤銷
- Token 僅在建立時顯示一次（ephemeral），之後無法再查看
