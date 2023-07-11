# Beanfun Discord Bot

這是一個允許多人在Discord上共享同一個Beanfun登入器的機器人。

* 此篇內容由chatGPT產生，還待改進。

## 安裝

首先，請確保你已經安裝了Docker。如果你還沒有安裝，請訪問[Docker](https://www.docker.com/)並按照指南進行安裝。

然後，你可以使用以下的命令來建立並運行Docker映像：

```bash

docker build -t beanfun-bot .
docker run -d -e BOT_TOKEN=<你的Discord bot token> -e LIMIT_GUILD=<你的Discord server id> beanfun-bot

```

## 環境變數

以下是可用的環境變數及其默認值：

- `LIMIT_GUILD`：伺服器ID（無默認值）
- `BOT_TOKEN`：Discord機器人token（無默認值）
- `LOGIN_TIME_OUT`：登入超時時間（默認值為180）
- `OTP_DISPLAY_TIME`：OTP顯示時間（默認值為20）
- `HIDDEN_PRIVATE_MESSAGE`：是否隱藏私人訊息（默認值為1）

## Discord Bot註冊

如果你還沒有Discord bot token，你需要在Discord Developer Portal中創建一個新的應用並註冊一個機器人來獲取token。以下是基本步驟：

1. 訪問[Discord Developer Portal](https://discord.com/developers/applications)。
2. 點擊“New Application”按鈕。
3. 給你的應用命名，然後點擊“Create”按鈕。
4. 在左側的導航欄中，點擊“Bot”菜單項。
5. 點擊“Add Bot”按鈕，然後在彈出的對話框中確認。
6. 在Bot頁面中，你可以看到你的token，你可以通過點擊“Copy”按鈕來複製它。

請注意，你應該要保護好你的token，不要讓它公開或分享給他人，因為有了token，任何人都可以使用你的機器人。

## 使用

當你已經完成以上步驟並成功運行你的機器人後，你就可以在Discord上使用它了。以下是可用的命令：

- `login`：登入
- `status`：獲取當前登入的賬號信息
- `game`：登入遊戲
- `set_logout_ttl`：設置自動登出時間
- `logout`：登出Beanfun

詳細的命令用法請參考源代碼。
