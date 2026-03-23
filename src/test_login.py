import asyncio
import base64
import sys
from urllib.parse import quote

from methods.beanfun import BeanfunLogin
from exceptions.beanfun_error import LoginTimeOutError

BASE_REDIRECT = "https://assets.taki.dog/html/beanfun-discord-redirect.html?redirect="


async def main():
    login = BeanfunLogin(channel_id="test")
    try:
        print("取得登入資訊中...")
        qr_info = await login.get_login_info()

        qr_bytes = base64.b64decode(qr_info.QRImage)
        output_path = "qr_login.png"
        with open(output_path, "wb") as f:
            f.write(qr_bytes)
        print(f"QR 圖片已儲存至: {output_path}")
        print(f"DeepLink: {BASE_REDIRECT}{quote(qr_info.DeepLink, safe='')}")

        print("\n等待掃碼登入中... (最多等待 120 秒)")
        for i in range(120):
            try:
                status = await login.get_login_status()
                if status.ResultCode == 1:
                    login.is_login = True
                    print("\n登入成功！")
                    break
                print(f"\r等待中... {i+1}s", end="", flush=True)
                await asyncio.sleep(1)
            except LoginTimeOutError:
                print("\n登入逾時")
                return
        else:
            print("\n等待超時，未完成登入")
            return

        point = await login.get_game_point()
        print(f"點數剩餘: {point.RemainPoint}")

        accounts = await login.get_maplestory_account_list()
        if not accounts:
            print("沒有找到遊戲帳號")
        else:
            print(f"\n遊戲帳號列表 ({len(accounts)} 個):")
            for acc in accounts:
                print(f"  名稱: {acc.account_name}  帳號: {acc.account}")
    except Exception as e:
        print(f"\n錯誤: {e}", file=sys.stderr)
        raise
    finally:
        await login.close_connection()


if __name__ == "__main__":
    asyncio.run(main())
