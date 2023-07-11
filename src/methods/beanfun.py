import asyncio
import json
import re
import time
from datetime import datetime
from typing import List

import aiohttp
from lxml import etree

from exceptions.beanfun_error import LoginTimeOutError
from utils.config import LOGIN_TIME_OUT
from utils.model import CheckLoginStatus, GamePointResponse, HeartBeatResponse, LoginQRInfo, MSAccountModel
from utils.util import SSL_CTX, decrypt_des_pkcs5_hex, extract_json


class BeanfunLogin:
    def __init__(self, channel_id, auto_logout_sec: int = -1) -> None:
        """
        Initialize a BeanfunLogin object.

        Args:
            channel_id (str): Channel ID for the login.
            auto_logout_sec (int, optional): Auto-logout timeout in seconds. Defaults to -1, meaning no auto-logout.
        """
        self.channel_id = channel_id
        self.is_login = False
        self.login_qr_data = None
        self.web_token = None
        self._create_login_time = 0
        self.skey = None
        self.game_account_list = None
        self.login_at = 0
        self.auto_logout_sec = auto_logout_sec

        # Setting up the TCP connection for the session.
        self._conn = aiohttp.TCPConnector(ssl=SSL_CTX)
        self.session = aiohttp.ClientSession(connector=self._conn)

    async def get_login_info(self) -> LoginQRInfo:
        """
        Retrieves the login info, including encrypted QR data.

        Returns:
            LoginQRInfo: Contains encrypted QR data.
        """
        # Logging out of the session and creating a new connection if already logged in
        if self.is_login:
            await self.logout()
            await self.close_connection()
            self.session = aiohttp.ClientSession(connector=self._conn)

        # Resetting the login-related variables
        self.is_login = False
        self.login_qr_data = None
        self.web_token = None
        self.skey = None
        self._create_login_time = time.time()

        # Sending GET request to the login URL
        res = await self.session.get(
            "https://tw.beanfun.com/beanfun_block/bflogin/default.aspx?service_code=999999&service_region=T0"
        )
        self.skey = res.request_info.url.query.get("skey")  # Extracting security key from the URL
        # Fetching QR data using the security key
        res = await self.session.get(
            f"https://tw.newlogin.beanfun.com/generic_handlers/get_qrcodeData.ashx?skey={self.skey}&startGame=&clientID="  # noqa: E501
        )  # noqa: E501

        result = await res.json()

        # Updating QR data for the login session
        self.login_qr_data = LoginQRInfo(**result)
        return self.login_qr_data

    async def get_login_status(self) -> CheckLoginStatus:
        """
        Checks the status of the current login.

        Returns:
            CheckLoginStatus: Contains the status of the login operation.

        Raises:
            LoginTimeOutError: If the login has timed out.
            ValueError: If login QR data is missing.
        """
        # Checking for login timeout
        if time.time() - self._create_login_time > LOGIN_TIME_OUT:
            raise LoginTimeOutError()
        # Ensuring that the login QR data exists
        if self.login_qr_data is None:
            raise ValueError("Required get login QR.")

        # Sending a POST request to check login status
        res = await self.session.post(
            "https://tw.newlogin.beanfun.com/generic_handlers/CheckLoginStatus.ashx",
            data={
                "status": self.login_qr_data.strEncryptData,
            },
        )
        # Parsing the JSON response to a CheckLoginStatus object
        response = CheckLoginStatus(**(await res.json()))
        if response.Result == 1:
            # Successful login, now fetching additional details...
            # ... code for that not annotated one by one here for brevity :P
            res = await self.session.get(
                f"https://tw.newlogin.beanfun.com/login/qr_step2.aspx?skey={self.skey}",
            )
            final_url = re.search(r'RedirectPage\("","./(.*?)"\)', await res.text())
            if final_url:
                final_url = final_url.group(1)
            final_res = await self.session.get(
                f"https://tw.newlogin.beanfun.com/login/{final_url}",
            )
            akey = final_res.request_info.url.query.get("akey")

            final_html = await final_res.text()
            # bfSecretCode_match = re.search(
            #     r'bfSecretCode = "(.*?)"', final_html)
            strWriteUrl_match = re.search(r'strWriteUrl = "(.*?)"', final_html)

            if strWriteUrl_match:
                strWriteUrl = strWriteUrl_match.group(1)
                res = await self.session.get(
                    strWriteUrl,
                )

            # if bfSecretCode_match:
            #     bfSecretCode = bfSecretCode_match.group(1)
            res = await self.session.post(
                "https://tw.beanfun.com/beanfun_block/bflogin/return.aspx",
                data={
                    "SessionKey": self.skey,
                    "AuthKey": akey,
                    "ServiceCode": "",
                    "ServiceRegion": "",
                    "ServiceAccountSN": "0",
                },
            )
            self.web_token = self.session.cookie_jar.filter_cookies("https://tw.beanfun.com").get("bfWebToken").value

        return response

    async def logout(self):
        """
        Logs out from the current session and resets the session variables.
        """
        # Removing login session via GET request
        await self.session.get("https://tw.newlogin.beanfun.com/generic_handlers/remove_bflogin_session.ashx")
        # Logging out from the service via GET request
        await self.session.get("https://tw.beanfun.com/logout.aspx?service=999999_T0")

        # Erasing web token via POST request
        await self.session.post(
            "https://tw.newlogin.beanfun.com/generic_handlers/erase_token.ashx", data={"web_token": "1"}
        )  # noqa: E501

        # If logged in, close current connection and open a new one
        if self.is_login:
            await self.close_connection()
            self.session = aiohttp.ClientSession(connector=self._conn)

        # Resetting the session variables
        self.is_login = False
        self.login_qr_data = None
        self.web_token = None
        self.game_account_list = None
        self.auto_logout_sec = -1
        self.skey = None

    async def get_heartbeat(self) -> HeartBeatResponse:
        """
        Checks the status of the current login periodically to maintain the login session.

        Returns:
            HeartBeatResponse: Contains the status of the heartbeat operation.

        """
        # If the session is set to auto-logout and the session has lasted longer than the auto-logout interval, logout.
        if self.auto_logout_sec > 0 and time.time() - self.login_at > self.auto_logout_sec:
            await self.logout()
            # Return a default heartbeat response when a logout occurs.
            return HeartBeatResponse(ResultData=None, Result=0, ResultMessage="")

        # Send a POST request to check login status
        res = await self.session.post(
            "https://tw.newlogin.beanfun.com/generic_handlers/CheckLoginStatus.ashx",
            data={
                "status": self.login_qr_data.strEncryptData,
            },
        )
        # Parse the response text and return a HeartBeatResponse object.
        result = await res.text()
        return HeartBeatResponse(**extract_json(result))

    async def get_game_point(self) -> GamePointResponse:
        """
        Fetches the remaining game points.

        Returns:
            GamePointResponse: Contains the status of the game point retrieval operation and the remaining points.

        """
        # Send a GET request to fetch remaining game points.
        res = await self.session.get(
            "https://tw.beanfun.com/beanfun_block/generic_handlers/get_remain_point.ashx?webtoken=1"
        )  # noqa: E501
        # Parse the response text and return a GamePointResponse object.
        result = await res.text()
        return GamePointResponse(**extract_json(result))

    async def close_connection(self):
        """
        Closes the current session.

        """
        await self.session.close()

    async def waiting_login_loop(self, callback_func):
        """
        This function waits for the login to complete or for a timeout.

        Args:
            callback_func (callable): The function to be called when login is complete or an error occurs.

        If the login is successful, it calls the callback function with a status of 1.
        If an error occurs, it calls the callback function with a status of -1.
        If it times out after waiting for 120 seconds, it calls the callback function with a status of -2.
        """
        if self.is_login:
            await callback_func(1)
            return
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

    async def get_maplestory_account_list(self) -> List["MSAccountModel"]:
        """
        Retrieves the list of Maplestory accounts associated with the current session.

        Returns:
            List[MSAccountModel]: List of Maplestory accounts.

        If the game account list has already been fetched, it returns the cached list.
        """
        if self.game_account_list is not None:
            return self.game_account_list

        # Sending a GET request to fetch the game account list
        res = await self.session.get(
            f"https://tw.beanfun.com/beanfun_block/auth.aspx?page_and_query=game_start.aspx%3Fservice_code_and_region%3D610074_T9&channel=game_zone&web_token={self.web_token}"  # noqa: E501
        )
        response = await res.text()

        # Parsing the HTML response
        root = etree.HTML(response)
        result = []
        # Iterating through the list of game accounts in the HTML
        for i in root.xpath('//div[@id="divServiceAccountList"]//li//div'):
            # Ignoring accounts that are not visible
            if i.get("visible") != "1":
                continue
            # Appending each account to the result list
            result.append(
                MSAccountModel(
                    account=i.get("id"),
                    account_name=i.text,
                    sn=i.get("sn"),
                )
            )

        # Storing the fetched game account list
        self.game_account_list = result

        return result

    async def get_account_otp(self, account: MSAccountModel) -> str:
        """
        Fetches the One-Time Password (OTP) for the given account.

        Args:
            account (MSAccountModel): The account to fetch the OTP for.

        Returns:
            str: The decrypted OTP.
        """
        d = datetime.now()

        # Formatting the current datetime as a string
        str_datetime = f"{d.year}{d.month:02d}{d.day:02d}{d.hour:02d}{d.minute:02d}{d.second:02d}{d.minute:02d}"

        # Sending a GET request with the formatted datetime, service details, and account serial number
        res = await self.session.get(
            f"https://tw.beanfun.com/beanfun_block/game_zone/game_start_step2.aspx?service_code=610074&service_region=T9&sotp={account.sn}&dt={str_datetime}"  # noqa: E501
        )

        html = await res.text()
        # Using regex to extract a specific data string from the HTML
        match = re.search(r"MyAccountData = ({.*?});", html)
        data_str = match.group(1) if match else None

        # Extracting the date string from the data string
        date_string = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", data_str).group(0)

        # Replacing the original date in the data string with a placeholder
        data_str = re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", "TEMP_DATE_STRING", data_str)

        # Converting the data string from JavaScript object format to JSON format
        data_str = re.sub(r"(\w+):", r'"\1":', data_str)
        data_str = data_str.replace("'", '"')
        data_str = data_str.replace("\\", "\\\\")  # escape backslashes

        # Parsing the JSON-formatted string into a Python dictionary
        data_json = json.loads(data_str)

        # Replacing the placeholder date in the dictionary with the original date
        data_json["ServiceAccountCreateTime"] = date_string

        # Extracting the polling key from the HTML
        match = re.search(r'"generic_handlers/get_result\.ashx\?meth=GetResultByLongPolling&key=([a-z0-9-]+)"', html)
        polling_key = match.group(1) if match else None

        # Sending POST request to record service start
        res = await self.session.post(
            "https://tw.beanfun.com/beanfun_block/generic_handlers/record_service_start.ashx",
            data={  # noqa: E501
                "service_code": "610074",
                "service_region": "T9",
                "service_account_id": account.account,
                "sotp": account.sn,
                "service_account_display_name": account.account_name,
                "service_account_create_time": date_string,
            },
        )

        # Getting cookies from server
        res = await self.session.get("https://tw.newlogin.beanfun.com/generic_handlers/get_cookies.ashx")  # noqa: E501
        match = re.search(r"var m_strSecretCode = '(.+?)';", await res.text())
        secret_code = match.group(1)

        # Parameters for getting OTP
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

        # Sending GET request to get OTP
        res = await self.session.get(
            "https://tw.beanfun.com/beanfun_block/generic_handlers/get_webstart_otp.ashx", params=params
        )  # noqa: E501
        data = await res.text()

        # Decrypting and returning the OTP
        return decrypt_des_pkcs5_hex(data)
