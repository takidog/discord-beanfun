import asyncio
import datetime
from typing import Any, Coroutine, Dict, List
import discord
from discord import app_commands
from discord.ext import commands
from methods.beanfun import BeanfunLogin

from utils.config import LIMIT_GUILD, LOGIN_TIME_OUT, OTP_DISPLAY_TIME
import qrcode


import io


class BeanfunCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.loop_list = []  # A list to keep track of all loops
        self.login_dict: Dict[str, BeanfunLogin] = {}  # A dictionary to keep track of all logins

    # This method is called when the cog is loaded
    async def cog_load(self) -> Coroutine[Any, Any, None]:
        return await super().cog_load()

    # This method is called when the cog is unloaded
    async def cog_unload(self) -> Coroutine[Any, Any, None]:
        # Cancel all loops in the loop_list
        for i in self.loop_list:
            i.cancel()
        # Log out and close all connections in the login_dict
        for i in self.login_dict.values():
            await i.logout()
            await i.close_connection()

        return await super().cog_unload()

    # A command to sync the bot with the current guild
    @commands.command()
    async def sync(self, ctx: commands.Context) -> None:
        fmt = await ctx.bot.tree.sync(guild=ctx.guild)
        await ctx.send(f"Synced {len(fmt)} commands to the current guild.")
        return

    # A command to get the login status of the account
    @app_commands.command(name="status", description="取得目前登入的帳號資訊")
    async def account(self, interaction: discord.Interaction):
        # Check if there is a login for the channel the command was called from
        if interaction.channel_id not in self.login_dict:
            await interaction.response.send_message("目前該頻道沒有登入器")
            return

        login = self.login_dict[interaction.channel_id]
        # Check if the login is currently logged in
        if not login.is_login:
            await interaction.response.send_message("目前該頻道尚未登入BF")
            return

        # Check the heartbeat of the login
        heartbeat = await login.get_heartbeat()
        if heartbeat.Result == 0:
            await interaction.response.send_message("帳號沒有靈壓了，需要重新登入")
            return

        # Get the remaining game points of the login
        point = await login.get_game_point()
        # Get a list of all the accounts of the login
        account_list_str = ""
        for i in await login.get_maplestory_account_list():
            account_list_str += f"帳號名稱: {i.account_name} 帳號: {i.account}\n"
        # Send the login information to the channel the command was called from
        await interaction.response.send_message(f"目前登入中，點數剩餘：{point.RemainPoint}\n{account_list_str}")
        await interaction.channel.send("----")  # noqa: E501
        # Check if auto logout is set
        if login.auto_logout_sec > 0:
            await interaction.channel.send(
                f'設有自動登出({login.auto_logout_sec}s)，將於`{datetime.datetime.fromtimestamp(login.login_at + login.auto_logout_sec).strftime("%Y-%m-%d %H:%M:%S")}` 登出'  # noqa: E501
            )
        else:
            await interaction.channel.send("目前沒有設定自動登出")  # noqa: E501

    # This is a command to login to the account

    @app_commands.command(name="login", description="登入")
    async def login(self, interaction: discord.Interaction):
        # Check if there is a login for the channel the command was called from
        # If not, create a new one
        if interaction.channel_id not in self.login_dict:
            self.login_dict[interaction.channel_id] = BeanfunLogin(channel_id=interaction.channel_id)
        # Retrieve the login associated with the channel ID
        login = self.login_dict[interaction.channel_id]
        # If the login is already logged in, inform the user that the current login status will be overwritten
        if login.is_login:
            await interaction.channel.send("目前該頻道已登入，會覆蓋登入狀態。")
        # Get the login details
        login_detail = await login.get_login_info()

        # Continue to generate a QR code for login, send it to the user, and start a loop to wait for
        # login status changes
        delete_message_list = []

        m1 = await interaction.channel.send(f"請於{LOGIN_TIME_OUT}s內完成登入", delete_after=LOGIN_TIME_OUT)
        delete_message_list.append(m1)
        qr = qrcode.make(
            data=f"https://beanfunstor.blob.core.windows.net/redirect/appCheck.html?url=beanfunapp://Q/gameLogin/gtw/{login_detail.strEncryptData}"  # noqa: E501
        )

        file = io.BytesIO()
        qr.save(file)
        file.seek(0)
        m2 = await interaction.channel.send(
            file=discord.File(fp=file, filename="image.png"), delete_after=LOGIN_TIME_OUT
        )
        delete_message_list.append(m2)

        m3 = await interaction.channel.send(
            f"https://beanfunstor.blob.core.windows.net/redirect/appCheck.html?url=beanfunapp://Q/gameLogin/gtw/{login_detail.strEncryptData}",  # noqa: E501
            delete_after=130,
            suppress_embeds=True,
        )
        delete_message_list.append(m3)

        loop = asyncio.get_event_loop()

        async def login_callback(status):
            if status == 1:
                await interaction.channel.send("登入成功")
                await asyncio.gather(*[i.delete() for i in delete_message_list])

                login = self.login_dict[interaction.channel_id]
                point = await login.get_game_point()
                account_list_str = ""
                for i in await login.get_maplestory_account_list():
                    account_list_str += f"帳號名稱: {i.account_name} 帳號: ||{i.account}||\n"
                await interaction.channel.send(f"目前登入中，點數剩餘：{point.RemainPoint}\n{account_list_str}")
                # login success
                pass
            elif status == -1:
                await interaction.channel.send("登入器錯誤:(")
                await asyncio.gather(*[i.delete() for i in delete_message_list])
            elif status == -2:
                await interaction.channel.send("晚了就不要了:(")
                await asyncio.gather(*[i.delete() for i in delete_message_list])

        self.loop_list.append(loop.create_task(login.waiting_login_loop(login_callback)))

    # This is a function to auto-complete game account names when the "game" command is used
    async def game_account_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        # ...
        # Retrieve the login associated with the channel ID
        # Then return a list of game account names

        if interaction.channel_id not in self.login_dict:
            await interaction.response.send_message("目前該頻道沒有登入器")
            return

        login = self.login_dict[interaction.channel_id]
        if not login.is_login:
            await interaction.response.send_message("目前該頻道尚未登入BF")
            return

        return [
            app_commands.Choice(name=account.account_name, value=account.account)
            for account in (await login.get_maplestory_account_list())
        ]

    # This is a command to login to the game
    @app_commands.command(name="game", description="登入遊戲")
    @app_commands.autocomplete(game_account=game_account_autocomplete)
    async def game(self, interaction: discord.Interaction, game_account: str):
        # ...
        # Retrieve the login associated with the channel ID
        # Check the login status and heartbeat, then log in to the game

        if interaction.channel_id not in self.login_dict:
            await interaction.response.send_message("目前該頻道沒有登入器")
            return

        login = self.login_dict[interaction.channel_id]
        if not login.is_login:
            await interaction.response.send_message("目前該頻道尚未登入BF")
            return

        heartbeat = await login.get_heartbeat()
        if heartbeat.Result == 0:
            await interaction.response.send_message("帳號沒有靈壓了，需要重新登入")
            return

        account_model = None
        for i in await login.get_maplestory_account_list():
            if i.account == game_account:
                account_model = i
        if account_model is None:
            await interaction.response.send_message("! 沒找到這個帳號")
            return

        await interaction.response.send_message(
            f"於{OTP_DISPLAY_TIME}s後刪除\n帳號名稱: {account_model.account_name}\n帳號: ||{account_model.account}||\n密碼: ||{await login.get_account_otp(account=account_model)}||",  # noqa: E501
            delete_after=OTP_DISPLAY_TIME,
        )

    # This is a command to set the auto logout time
    @app_commands.command(name="set_logout_ttl", description="設定自動登出時長")
    async def set_ttl(self, interaction: discord.Interaction, ttl: int):
        # ...
        # Retrieve the login associated with the channel ID
        # Check the login status, then set the auto logout time

        if interaction.channel_id not in self.login_dict:
            await interaction.response.send_message("目前該頻道沒有登入器")
            return

        login = self.login_dict[interaction.channel_id]
        if not login.is_login:
            await interaction.response.send_message("目前該頻道尚未登入BF")
            return

        login.auto_logout_sec = ttl

        await interaction.response.send_message(f"已設定為 {login.auto_logout_sec}s後登出")

    # This is a command to logout from the account
    @app_commands.command(name="logout", description="登出Beanfun")
    async def logout(self, interaction: discord.Interaction):
        # ...
        # Retrieve the login associated with the channel ID
        # Check the login status, then log out from the account
        if interaction.channel_id not in self.login_dict:
            await interaction.response.send_message("目前該頻道沒有登入器")
            return

        login = self.login_dict[interaction.channel_id]
        if not login.is_login:
            await interaction.response.send_message("目前該頻道尚未登入BF")
            return

        await login.logout()
        await interaction.response.send_message("ok")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BeanfunCog(bot), guilds=[discord.Object(id=i) for i in LIMIT_GUILD])
