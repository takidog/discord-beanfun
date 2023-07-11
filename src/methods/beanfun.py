import asyncio
from datetime import datetime
import json
import re
import time
from typing import List

import aiohttp
import qrcode

from exceptions.beanfun_error import LoginTimeOutError
from utils.config import LOGIN_TIME_OUT
from utils.model import (CheckLoginStatus, GamePointResponse,
                         HeartBeatResponse, LoginQRInfo, MSAccountModel)
from utils.util import SSL_CTX, decrypt_des_pkcs5_hex, extract_json
from lxml import etree


class BeanfunLogin:

    def __init__(self, channel_id, auto_logout_sec: int = -1) -> None:
        self.channel_id = channel_id
        self.is_login = False
        self.login_qr_data = None
        self.web_token = None
        self._create_login_time = 0
        self.skey = None
        self._conn = aiohttp.TCPConnector(ssl=SSL_CTX)
        self.game_account_list = None
        self.login_at = 0
        self.auto_logout_sec = auto_logout_sec

        self.session = aiohttp.ClientSession(connector=self._conn)

    async def get_login_info(self) -> LoginQRInfo:
        if self.is_login:

            self.close_connection()
            self.session = aiohttp.ClientSession(connector=self._conn)

        self.is_login = False
        self.login_qr_data = None
        self.web_token = None
        self.skey = None
        self._create_login_time = time.time()

        res = await self.session.get("https://tw.beanfun.com/beanfun_block/bflogin/default.aspx?service_code=999999&service_region=T0")  # noqa: E501
        self.skey = res.request_info.url.query.get('skey')
        res = await self.session.get(f"https://tw.newlogin.beanfun.com/generic_handlers/get_qrcodeData.ashx?skey={self.skey}&startGame=&clientID=")  # noqa: E501

        result = await res.json()

        self.login_qr_data = LoginQRInfo(**result)
        return self.login_qr_data

    async def get_login_status(self) -> CheckLoginStatus:
        if time.time()-self._create_login_time > LOGIN_TIME_OUT:
            raise LoginTimeOutError()
        if self.login_qr_data is None:
            raise ValueError("Required get login qr.")

        res = await self.session.post(
            "https://tw.newlogin.beanfun.com/generic_handlers/CheckLoginStatus.ashx",
            data={
                "status": self.login_qr_data.strEncryptData,
            }
        )
        response = CheckLoginStatus(**(await res.json()))
        if response.Result == 1:
            res = await self.session.get(
                f'https://tw.newlogin.beanfun.com/login/qr_step2.aspx?skey={self.skey}',


            )
            final_url = re.search(r'RedirectPage\("","./(.*?)"\)', await res.text())
            if final_url:
                final_url = final_url.group(1)
            final_res = await self.session.get(
                f'https://tw.newlogin.beanfun.com/login/{final_url}',


            )
            akey = final_res.request_info.url.query.get("akey")

            final_html = await final_res.text()
            # bfSecretCode_match = re.search(
            #     r'bfSecretCode = "(.*?)"', final_html)
            strWriteUrl_match = re.search(
                r'strWriteUrl = "(.*?)"', final_html)

            if strWriteUrl_match:
                strWriteUrl = strWriteUrl_match.group(1)
                res = await self.session.get(
                    strWriteUrl,

                )

            # if bfSecretCode_match:
            #     bfSecretCode = bfSecretCode_match.group(1)
            #     self.web_token = bfSecretCode
            res = await self.session.post(
                "https://tw.beanfun.com/beanfun_block/bflogin/return.aspx",
                data={
                    'SessionKey': self.skey,
                    'AuthKey': akey,
                    'ServiceCode':	'',
                    'ServiceRegion': '',
                    'ServiceAccountSN':	'0',
                },
            )
            cookies = self.session.cookie_jar
            self.web_token = cookies.filter_cookies(
                'https://tw.beanfun.com').get('bfWebToken').value

        return response

    async def logout(self):

        await self.session.get('https://tw.newlogin.beanfun.com/generic_handlers/remove_bflogin_session.ashx')
        await self.session.get('https://tw.beanfun.com/logout.aspx?service=999999_T0')

        await self.session.post('https://tw.newlogin.beanfun.com/generic_handlers/erase_token.ashx', data={'web_token': '1'})  # noqa: E501

        if self.is_login:

            self.close_connection()
            self.session = aiohttp.ClientSession(connector=self._conn)

        self.is_login = False
        self.login_qr_data = None
        self.web_token = None
        self.auto_logout_sec = -1
        self.skey = None

    async def get_heartbeat(self) -> HeartBeatResponse:
        if self.auto_logout_sec > 0 and time.time() - self.login_at > self.auto_logout_sec:
            await self.logout()
            return HeartBeatResponse(ResultData=None, Result=0, ResultMessage="")

        res = await self.session.post(
            "https://tw.newlogin.beanfun.com/generic_handlers/CheckLoginStatus.ashx",
            data={
                "status": self.login_qr_data.strEncryptData,
            }
        )
        result = await res.text()

        return HeartBeatResponse(**extract_json(result))

    async def get_game_point(self) -> GamePointResponse:

        res = await self.session.get(
            "https://tw.beanfun.com/beanfun_block/generic_handlers/get_remain_point.ashx?webtoken=1")  # noqa: E501
        result = await res.text()

        return GamePointResponse(**extract_json(result))

    async def close_connection(self):
        await self.session.close()

    async def waiting_login_loop(self, callback_func):
        for _ in range(120):
            try:
                login_status = await self.get_login_status()

                if login_status.Result == 1:
                    self.is_login = True
                    self.login_at = time.time()
                    await callback_func(1)
                    return
                await asyncio.sleep(1)
            except Exception as e:
                print(e)
                await callback_func(-1)
                return

        await callback_func(-2)
        return

    async def get_maplestory_account_list(self) -> List['MSAccountModel']:
        if self.game_account_list is not None:
            return self.game_account_list

        res = await self.session.get(f"https://tw.beanfun.com/beanfun_block/auth.aspx?page_and_query=game_start.aspx%3Fservice_code_and_region%3D610074_T9&channel=game_zone&web_token={self.web_token}")  # noqa: E501
        response = await res.text()
        root = etree.HTML(response)
        result = []
        for i in root.xpath('//div[@id="divServiceAccountList"]//li//div'):
            if i.get("visible") != "1":
                continue
            result.append(
                MSAccountModel(
                    account=i.get("id"),
                    account_name=i.text,
                    sn=i.get("sn"),
                )
            )
        self.game_account_list = result

        return result

    async def get_account_otp(self, account: MSAccountModel) -> str:
        d = datetime.now()

        # Format the date and time
        str_datetime = f"{d.year}{d.month:02d}{d.day:02d}{d.hour:02d}{d.minute:02d}{d.second:02d}{d.minute:02d}"

        res = await self.session.get(f"https://tw.beanfun.com/beanfun_block/game_zone/game_start_step2.aspx?service_code=610074&service_region=T9&sotp={account.sn}&dt={str_datetime}")  # noqa: E501

        html = await res.text()
        # Use regex to find the content of MyAccountData
        match = re.search(r'MyAccountData = ({.*?});', html)
        data_str = match.group(1) if match else None

        date_pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
        date_string = re.search(date_pattern, data_str).group(0)

        # Replace the date with a simple string
        date_replacement = "TEMP_DATE_STRING"
        data_str = re.sub(date_pattern, date_replacement, data_str)

        # Convert JavaScript objects to JSON
        # enclose the keys within double quotes
        data_str = re.sub(r'(\w+):', r'"\1":', data_str)
        # replace single quotes with double quotes
        data_str = data_str.replace('\'', '\"')
        data_str = data_str.replace('\\', '\\\\')  # escape backslashes

        # parse the JSON string to Python dict
        data_json = json.loads(data_str)

        # Replace the simple string back with the original date
        data_json["ServiceAccountCreateTime"] = date_string

        match = re.search(
            r'"generic_handlers/get_result\.ashx\?meth=GetResultByLongPolling&key=([a-z0-9-]+)"', html)
        polling_key = match.group(1) if match else None

        res = await self.session.post("https://tw.beanfun.com/beanfun_block/generic_handlers/record_service_start.ashx", data={  # noqa: E501
            "service_code": "610074",
            "service_region": "T9",
            "service_account_id": account.account,
            "sotp": account.sn,
            "service_account_display_name": account.account_name,
            "service_account_create_time": date_string,
        })

        res = await self.session.get("https://tw.newlogin.beanfun.com/generic_handlers/get_cookies.ashx")  # noqa: E501
        match = re.search(r"var m_strSecretCode = '(.+?)';", await res.text())
        secret_code = match.group(1)

        params = {
            "sn": polling_key,
            "WebToken": self.web_token,
            "SecretCode": secret_code,
            "ppppp": "F9B45415B9321DB9635028EFDBDDB44B4012B05F95865CB8909B2C851CFE1EE11CB784F32E4347AB7001A763100D90768D8A4E30BCC3E80C",  # noqa: E501
            "ServiceCode": "610074",
            "ServiceRegion": "T9",
            "ServiceAccount": account.account,
            "CreateTime": date_string,
            "d": int(datetime.now().timestamp() * 1000),
        }

        res = await self.session.get("https://tw.beanfun.com/beanfun_block/generic_handlers/get_webstart_otp.ashx", params=params)  # noqa: E501
        data = await res.text()

        return decrypt_des_pkcs5_hex(data)


async def main():

    ctl = BeanfunLogin()
    await ctl.get_login_info()

    await ctl.get_login_status()
    print(
        f"https://beanfunstor.blob.core.windows.net/redirect/appCheck.html?url=beanfunapp://Q/gameLogin/gtw/{ctl.login_qr_data.strEncryptData}")  # noqa: E501
    im = qrcode.make(
        data=f"https://beanfunstor.blob.core.windows.net/redirect/appCheck.html?url=beanfunapp://Q/gameLogin/gtw/{ctl.login_qr_data.strEncryptData}")  # noqa: E501
    im.save("qr.png")
    for _ in range(120):
        login_status = await ctl.get_login_status()
        if login_status.Result == 1:

            break
        await asyncio.sleep(1)

    for i in await ctl.get_maplestory_account_list():
        print(await ctl.get_account_otp(i))

    await ctl.close_connection()


if __name__ == "__main__":
    asyncio.run(main())


"https://tw.newlogin.beanfun.com/generic_handlers/get_qrcodeData.ashx?skey=202307dcb4346732cd4f&startGame=&clientID="
