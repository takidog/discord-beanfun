"""
HTTP API Server — independent of Discord cogs.

Shares state with the bot only through:
  - bot.login_dict   (Dict[channel_id, BeanfunLogin])
  - bot.token_db     (TokenDatabase)
  - bot.get_channel() (for Discord notifications)
"""

import json
import logging
from typing import Optional

from aiohttp import web

from database.token_db import TokenDatabase, TokenRecord

logger = logging.getLogger("api.server")
_GUARD_HEADER_NAME = "X-Beanfun-Guard"
_GUARD_HEADER_VALUE = "discord-beanfun"


def _json_response(data: dict, status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(data, ensure_ascii=False),
        status=status,
        content_type="application/json",
    )


def _error(message: str, status: int = 400) -> web.Response:
    return _json_response({"error": message}, status=status)


async def _extract_token_record(request: web.Request) -> Optional[TokenRecord]:
    """Validate Bearer token from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    raw_token = auth[7:]
    db: TokenDatabase = request.app["token_db"]
    return await db.validate_token(raw_token)


def _has_stealth_signature(request: web.Request) -> bool:
    """Stealth gate: only accept specific guard header/value."""
    guard = request.headers.get(_GUARD_HEADER_NAME)
    if guard is None:
        return False
    return guard.strip().lower() == _GUARD_HEADER_VALUE


@web.middleware
async def auth_middleware(request: web.Request, handler):
    # Guard check first.
    if not _has_stealth_signature(request):
        return _error("Unauthorized: invalid guard header", 401)

    record = await _extract_token_record(request)
    if record is None:
        return _error("Unauthorized: invalid or expired token", 401)
    request["token_record"] = record
    return await handler(request)


async def handle_status(request: web.Request) -> web.Response:
    record: TokenRecord = request["token_record"]
    bot = request.app["bot"]
    login_dict = bot.login_dict

    login = login_dict.get(record.channel_id)
    logged_in = login is not None and login.is_login

    return _json_response({
        "logged_in": logged_in,
        "channel_name": record.channel_name,
        "app_name": record.app_name,
    })


async def handle_get_accounts(request: web.Request) -> web.Response:
    record: TokenRecord = request["token_record"]
    bot = request.app["bot"]
    login_dict = bot.login_dict

    login = login_dict.get(record.channel_id)
    if login is None or not login.is_login:
        return _error("Channel is not logged in", 403)

    try:
        account_list = await login.get_maplestory_account_list()
    except Exception as e:
        logger.exception("Failed to get account list")
        return _error(f"Failed to get account list: {e}", 500)

    accounts = [
        {"account_name": a.account_name, "account": a.account}
        for a in account_list
    ]
    return _json_response({"accounts": accounts})


async def handle_post_account(request: web.Request) -> web.Response:
    record: TokenRecord = request["token_record"]
    bot = request.app["bot"]
    login_dict = bot.login_dict

    login = login_dict.get(record.channel_id)
    if login is None or not login.is_login:
        return _error("Channel is not logged in", 403)

    try:
        body = await request.json()
    except Exception:
        return _error("Invalid JSON body", 400)

    account_id = body.get("account")
    if not account_id:
        return _error("Missing 'account' field in request body", 400)

    try:
        account_list = await login.get_maplestory_account_list()
    except Exception as e:
        logger.exception("Failed to get account list")
        return _error(f"Failed to get account list: {e}", 500)

    account_model = None
    for a in account_list:
        if a.account == account_id:
            account_model = a
            break

    if account_model is None:
        return _error("Account not found", 404)

    try:
        otp = await login.get_account_otp(account=account_model)
    except Exception as e:
        logger.exception("Failed to get OTP")
        return _error(f"Failed to get OTP: {e}", 500)

    try:
        channel = bot.get_channel(record.channel_id)
        if channel:
            await channel.send(
                f"應用程式 **{record.app_name}** 取得了帳號 "
                f"{account_model.account_name} 的密碼"
            )
    except Exception:
        logger.exception("Failed to send Discord notification")

    return _json_response({
        "account_name": account_model.account_name,
        "account": account_model.account,
        "otp": otp,
    })


def create_api_app(bot, db: TokenDatabase) -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app["bot"] = bot
    app["token_db"] = db

    app.router.add_get("/status", handle_status)
    app.router.add_get("/account", handle_get_accounts)
    app.router.add_post("/account", handle_post_account)

    return app
