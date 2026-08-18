import asyncio
import json
import re
import time
from datetime import datetime
from typing import List
from urllib.parse import unquote

import aiohttp
from Crypto.Cipher import DES
from lxml import etree

from exceptions.beanfun_error import LoginTimeOutError
from utils.config import LOGIN_TIME_OUT
from utils.model import (
    CheckLoginStatus,
    GamePointResponse,
    HeartBeatResponse,
    LoginQRInfo,
    MSAccountModel,
)
from utils import launcher_params
from utils.util import SSL_CTX, decrypt_des_pkcs5_hex, extract_json

# Browser fingerprint sent on every request. Beanfun's risk engine flags
# sessions whose page-fetch GETs don't look like a real browser, and a
# flagged session gets reaped early.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"  # noqa: E501
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    # Chrome major must stay in sync with USER_AGENT, a mismatch is itself
    # a bot signal.
    "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

_SKEY_RE = re.compile(r"[sp][Ss]?[Kk]ey=([^&]+)")
_INPUT_TAG_RE = re.compile(r"<input[^>]+>", re.I | re.S)
_INPUT_NAME_RE = re.compile(r"""name\s*=\s*['"]([^'"]+)['"]""", re.I)
_INPUT_VALUE_RE = re.compile(r"""value\s*=\s*['"]([^'"]*)['"]""", re.I)
_INPUT_SUBMIT_RE = re.compile(r"""type\s*=\s*['"]submit['"]""", re.I)


def _dt_compact() -> str:
    """Cache buster for game_zone/*.aspx: Y(M-1)DDhhmmssfff, month 0-indexed
    and not zero-padded (the portal's JS uses Date.getMonth())."""
    n = datetime.now()
    return (
        f"{n.year}{n.month - 1}{n.day:02d}{n.hour:02d}"
        f"{n.minute:02d}{n.second:02d}{n.microsecond // 1000:03d}"
    )


def _decrypt_launch_data(data: str) -> dict:
    """
    Decode the launch payload the game page hands to the native launcher.

    The first character selects both a substitution table and where the DES
    key sits. Every remaining character is replaced by its index in that
    table, which turns the payload into hex; the 8 characters at the key
    offset are the ASCII DES key and the rest is the ciphertext. The
    plaintext is a `&&&&`-joined list of key=value pairs holding, among
    others, the LaunchTicket.
    """
    n = int(data[0], 16)
    table = launcher_params.get()["tables"][n % 4]
    normalized = "".join(format(table.index(c), "x") for c in data[1:])

    key_at = n + 1
    key = normalized[key_at:key_at + 8].encode("ascii")
    cipher = bytes.fromhex(normalized[:key_at] + normalized[key_at + 8:])
    plain = DES.new(key, DES.MODE_ECB).decrypt(cipher).rstrip(b"\0").decode("utf-8")

    result = {}
    for segment in plain.split(";")[0].split("&&&&"):
        if "=" in segment:
            name, value = segment.split("=", 1)
            result[name] = value
    return result


def _extract_hidden_inputs(html: str) -> List[tuple]:
    """
    Scrape every non-submit <input> in document order. The SendLogin page
    stashes opaque session tokens there and return.aspx expects all of them
    back - including ServiceCode / ServiceRegion, which the page renders
    without a value attribute and which therefore count as empty strings.
    """
    result = []
    for tag in _INPUT_TAG_RE.findall(html):
        if _INPUT_SUBMIT_RE.search(tag):
            continue
        name = _INPUT_NAME_RE.search(tag)
        if not name:
            continue
        value = _INPUT_VALUE_RE.search(tag)
        result.append((name.group(1), value.group(1) if value else ""))
    return result


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
        self.heartbeat_worker = None

        # Setting up the TCP connection for the session.
        self._conn = aiohttp.TCPConnector(ssl=SSL_CTX)
        self.session = aiohttp.ClientSession(
            connector=self._conn, headers=DEFAULT_HEADERS
        )

        self.proxy = None 

        original_request = self.session._request

        async def request_with_proxy(method, url, **kwargs):
            if self.proxy and "proxy" not in kwargs:
                kwargs["proxy"] = self.proxy
            return await original_request(method, url, **kwargs)

        self.session._request = request_with_proxy

    async def get_login_info(self) -> LoginQRInfo:
        """
        Retrieves the login info, including QR image and DeepLink.

        Returns:
            LoginQRInfo: Contains QR image (base64) and DeepLink.
        """

        await self.logout()

        self._create_login_time = time.time()

        # The whole session is bound to whichever portal mints the skey.
        # Going through m.beanfun.com yields a token the strict tw endpoints
        # (get_webstart_otp) reject, so start on the tw portal.
        res = await self.session.get(
            "https://tw.beanfun.com/beanfun_block/bflogin/default.aspx?service=999999_T0"
        )
        match = _SKEY_RE.search(str(res.url))
        if not match:
            raise ValueError("Failed to get skey")
        self.skey = match.group(1)

        res = await self.session.get(
            f"https://login.beanfun.com/Login/Index?pSKey={self.skey}",
            headers={"Accept": "text/html"},
        )
        html = await res.text()
        match = re.search(
            r'name="__RequestVerificationToken"[^>]*value="([^"]*)"', html
        )
        if not match:
            raise ValueError("Failed to get RequestVerificationToken")
        self._verification_token = match.group(1)

        res = await self.session.get(
            f"https://login.beanfun.com/Login/InitLogin?pSKey={self.skey}",
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": f"https://login.beanfun.com/Login/Index?pSKey={self.skey}",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://login.beanfun.com",
            },
        )
        result = await res.json()
        result_data = result.get("ResultData", {})

        self.login_qr_data = LoginQRInfo(**result_data)
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

        _login_index_headers = {
            "Accept": "application/json, text/plain, */*",
            "RequestVerificationToken": self._verification_token,
            "Referer": f"https://login.beanfun.com/Login/Index?pSKey={self.skey}",
        }

        res = await self.session.post(
            "https://login.beanfun.com/QRLogin/CheckLoginStatus",
            headers={
                **_login_index_headers,
                "Origin": "https://login.beanfun.com",
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": "0",
            },
            data=b"",
        )
        response = CheckLoginStatus(**(await res.json()))
        if response.ResultCode == 1:
            # QRLogin → 取得 bfSecretCode cookie
            await self.session.get(
                "https://login.beanfun.com/QRLogin/QRLogin",
                headers=_login_index_headers,
            )

            # SendLogin → 取回整份表單(不只 AuthKey / SessionKey)
            res = await self.session.get(
                "https://login.beanfun.com/Login/SendLogin",
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",  # noqa: E501
                    "Referer": f"https://login.beanfun.com/Login/Index?pSKey={self.skey}",
                },
            )

            send_login_html = await res.text()
            form_data = _extract_hidden_inputs(send_login_html)
            if not form_data:
                raise ValueError("SendLogin returned no form data")

            # POST return.aspx，不跟隨 redirect。這一跳拿到的 bfWebToken 是暫時的，
            # 只是為了推進 server 端 session 狀態。
            await self.session.post(
                "https://tw.beanfun.com/beanfun_block/bflogin/return.aspx",
                data=aiohttp.FormData(form_data),
                headers={"Referer": "https://login.beanfun.com/"},
                allow_redirects=False,
            )

            # LoginCompleted：再 POST 一次 return.aspx。真正長效的 bfWebToken 是
            # 這一跳之後留在 cookie jar 的值。
            await self.session.post(
                "https://tw.beanfun.com/beanfun_block/bflogin/return.aspx",
                data={
                    "SessionKey": self.skey,
                    "AuthKey": "OK",
                    "ServiceCode": "",
                    "ServiceRegion": "",
                    "ServiceAccountSN": "0",
                },
                headers={"Referer": "https://login.beanfun.com/"},
            )
            self.web_token = (
                self.session.cookie_jar.filter_cookies("https://beanfun.com")
                .get("bfWebToken")
                .value
            )

        return response

    async def logout(self):
        """
        Logs out from the current session and resets the session variables.
        """
        # Removing login session via GET request
        await self.session.get(
            "https://tw.newlogin.beanfun.com/generic_handlers/remove_bflogin_session.ashx"
        )
        # Logging out from the service via GET request
        await self.session.get("https://tw.beanfun.com/logout.aspx?service=999999_T0")

        # Erasing web token via POST request
        await self.session.post(
            "https://tw.newlogin.beanfun.com/generic_handlers/erase_token.ashx",
            data={"web_token": "1"},
        )  # noqa: E501

        # Resetting the session variables
        self.is_login = False
        self.login_qr_data = None
        self.web_token = None
        self.game_account_list = None
        self.auto_logout_sec = -1
        self.skey = None
        if self.heartbeat_worker is not None:
            self.heartbeat_worker.cancel()
            self.heartbeat_worker = None

        self.session.cookie_jar.clear()

    async def get_heartbeat(self) -> HeartBeatResponse:
        """
        Checks the status of the current login periodically to maintain the login session.

        Returns:
            HeartBeatResponse: Contains the status of the heartbeat operation.

        """
        # If the session is set to auto-logout and the session has lasted longer than the auto-logout interval, logout.
        if (
            self.auto_logout_sec > 0
            and time.time() - self.login_at > self.auto_logout_sec
        ):
            await self.logout()
            # Return a default heartbeat response when a logout occurs.
            return HeartBeatResponse(ResultCode=0, ResultDesc="", MainAccountID="")

        # Send a POST request to check login status
        res = await self.session.get(
            "https://tw.beanfun.com/beanfun_block/generic_handlers/echo_token.ashx?webtoken=1"
        )
        # Parse the response text and return a HeartBeatResponse object.
        result = await res.text()

        # The request is only useful for its side effect of resetting the
        # server's inactivity timer. A body we cannot parse means the response
        # shape changed, not that the session died - never log out on it.
        try:
            model = HeartBeatResponse(**extract_json(result, double_quotes=True))
        except Exception:
            return HeartBeatResponse(ResultCode=1, ResultDesc="", MainAccountID="")

        if model.ResultCode == 0:
            await self.logout()

        return model

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

    async def heartbeat_loop(self, status_change_callback):
        if self.heartbeat_worker is not None:
            self.heartbeat_worker.cancel()
        if not self.is_login:
            return

        async def _worker(status_change_callback):
            while True:
                try:
                    res = await self.get_heartbeat()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    # A transient failure must not kill the keep-alive loop,
                    # the next tick is the retry.
                    print(f"heartbeat failed, retrying next tick: {e}")
                else:
                    if res.ResultCode == 0:
                        await status_change_callback(-1)
                        break

                await asyncio.sleep(60)

        loop = asyncio.get_event_loop()
        self.heartbeat_worker = loop.create_task(_worker(status_change_callback))

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
            login_status = await self.get_login_status()
            try:
                if login_status.ResultCode == 1:
                    self.is_login = True
                    self.login_at = time.time()
                    await callback_func(1)
                    return
                await asyncio.sleep(1)
            except Exception:
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
        # Sending a GET request with the formatted datetime, service details, and account serial number
        step2_url = (
            "https://tw.beanfun.com/beanfun_block/game_zone/game_start_step2.aspx"
            f"?service_code=610074&service_region=T9&sotp={account.sn}&dt={_dt_compact()}"
        )
        res = await self.session.get(step2_url)
        # The generic_handlers reject requests without a same-domain referrer.
        referer = {"Referer": step2_url}

        html = await res.text()
        # Using regex to extract a specific data string from the HTML
        match = re.search(r"MyAccountData = ({.*?});", html)
        data_str = match.group(1) if match else None

        # Extracting the date string from the data string
        date_string = re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", data_str).group(
            0
        )

        # Replacing the original date in the data string with a placeholder
        data_str = re.sub(
            r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", "TEMP_DATE_STRING", data_str
        )

        # Converting the data string from JavaScript object format to JSON format
        data_str = re.sub(r"(\w+):", r'"\1":', data_str)
        data_str = data_str.replace("'", '"')
        data_str = data_str.replace("\\", "\\\\")  # escape backslashes

        # Parsing the JSON-formatted string into a Python dictionary
        data_json = json.loads(data_str)

        # Replacing the placeholder date in the dictionary with the original date
        data_json["ServiceAccountCreateTime"] = date_string

        # The launch payload the page hands to the native game launcher. `data`
        # carries the LaunchTicket the OTP endpoint wants.
        match = re.search(r'"sn"\s*:\s*"([^"]+)"', html)
        launch_sn = match.group(1) if match else None
        match = re.search(r'"data"\s*:\s*"([^"]+)"', html)
        if not match:
            raise ValueError("game_start_step2 has no launch data")
        launch_data = match.group(1)

        # Per-request token the page appends to the record_service_start body.
        match = re.search(
            r'MyAccountData\.ServiceAccountCreateTime \+ "&(.*?)=(.*?)";', html
        )
        unk_data = (match.group(1), unquote(match.group(2))) if match else None

        # Sending POST request to record service start
        record_form = {  # noqa: E501
            "service_code": "610074",
            "service_region": "T9",
            "service_account_id": account.account,
            "sotp": account.sn,
            "service_account_display_name": account.account_name,
            "service_account_create_time": date_string,
        }
        if unk_data:
            record_form[unk_data[0]] = unk_data[1]
        res = await self.session.post(
            "https://tw.beanfun.com/beanfun_block/generic_handlers/record_service_start.ashx",
            data=record_form,
            headers=referer,
        )

        # The native launcher decrypts the launch payload locally and posts the
        # LaunchTicket it finds inside. Do the same.
        launch_params = _decrypt_launch_data(launch_data)
        launch_ticket = launch_params.get("LaunchTicket")
        if not launch_ticket:
            raise ValueError("launch data carries no LaunchTicket")

        launcher = launcher_params.get()
        res = await self.session.post(
            "https://tw.beanfun.com/beanfun_block/generic_handlers/get_webstart_otp_v2.ashx",
            data=json.dumps(
                {
                    "SN": launch_sn,
                    "LaunchTicket": launch_ticket,
                    "CV": launcher["cv"],
                    "Hash": launcher["hash"],
                    "arch": launcher["arch"],
                }
            ),
            headers={**referer, "Content-Type": "application/json; charset=utf-8"},
        )
        result = await res.json(content_type=None)
        if result.get("result") != 1:
            raise ValueError(f"OTP request rejected: {result.get('message')}")

        # Decrypting and returning the OTP
        return decrypt_des_pkcs5_hex(result["data"])
