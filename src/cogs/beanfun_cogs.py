import asyncio
from typing import Any, Coroutine, Dict, List
import discord
from discord import app_commands
from discord.ext import commands
from methods.beanfun import BeanfunLogin

from utils.config import LIMIT_GUILD
import qrcode


import io


async def test():
    try:
        while True:
            print("Running...")
            await asyncio.sleep(1)  # 假設這是一個會一直執行的任務
    except asyncio.CancelledError:
        print("Task was cancelled")
        raise


class BeanfunCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.loop_list = []
        self.login_dict: Dict[str, BeanfunLogin] = {

        }

    async def cog_load(self) -> Coroutine[Any, Any, None]:

        return await super().cog_load()

    async def cog_unload(self) -> Coroutine[Any, Any, None]:
        for i in self.loop_list:
            i.cancel()
        for i in self.login_dict.values():
            await i.close_connection()

        return await super().cog_unload()

    @commands.command()
    async def sync(self, ctx: commands.Context) -> None:
        fmt = await ctx.bot.tree.sync(guild=ctx.guild)
        await ctx.send(
            f"Synced {len(fmt)} commands to the current guild."
        )
        return

    @app_commands.command(name="status", description="取得目前登入的帳號資訊")
    async def account(self, interaction: discord.Interaction):
        if interaction.channel_id not in self.login_dict:
            await interaction.response.send_message('目前該頻道沒有登入器')
            return

        login = self.login_dict[interaction.channel_id]
        if not login.is_login:
            await interaction.response.send_message('目前該頻道尚未登入BF')
            return

        heartbeat = await login.get_heartbeat()
        if heartbeat.Result == 0:
            await interaction.response.send_message('帳號沒有靈壓了，需要重新登入')
            return

        point = await login.get_game_point()
        account_list_str = ""
        for i in await login.get_maplestory_account_list():
            account_list_str += f"帳號名稱: {i.account_name} 帳號: {i.account}\n"
        await interaction.response.send_message(f'目前登入中，點數剩餘：{point.RemainPoint}\n{account_list_str}')

    @app_commands.command(name="login", description="登入")
    async def login(self, interaction: discord.Interaction):
        await interaction.response.send_message('ok')

        if interaction.channel_id not in self.login_dict:
            self.login_dict[interaction.channel_id] = BeanfunLogin(
                channel_id=interaction.channel_id)

        login = self.login_dict[interaction.channel_id]
        if login.is_login:
            await interaction.channel.send('目前該頻道已登入，會覆蓋登入狀態。')

        login_detail = await login.get_login_info()

        delete_message_list = []

        m1 = await interaction.channel.send('請於120s內完成登入', delete_after=130)
        delete_message_list.append(m1)
        qr = qrcode.make(
            data=f"https://beanfunstor.blob.core.windows.net/redirect/appCheck.html?url=beanfunapp://Q/gameLogin/gtw/{login_detail.strEncryptData}")  # noqa: E501

        file = io.BytesIO()
        qr.save(file)
        file.seek(0)
        m2 = await interaction.channel.send(file=discord.File(fp=file, filename='image.png'), delete_after=130)
        delete_message_list.append(m2)

        m3 = await interaction.channel.send(f"https://beanfunstor.blob.core.windows.net/redirect/appCheck.html?url=beanfunapp://Q/gameLogin/gtw/{login_detail.strEncryptData}", delete_after=130)  # noqa: E501
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
                    account_list_str += f"帳號名稱: {i.account_name} 帳號: {i.account}\n"
                await interaction.channel.send(f'目前登入中，點數剩餘：{point.RemainPoint}\n{account_list_str}')
                # login success
                pass
            elif status == -1:
                # error
                pass
            elif status == -2:
                # timeout
                pass

        self.loop_list.append(
            loop.create_task(login.waiting_login_loop(login_callback))
        )

    async def game_account_autocomplete(
            self, interaction: discord.Interaction, current: str,
    ) -> List[app_commands.Choice[str]]:

        if interaction.channel_id not in self.login_dict:
            await interaction.response.send_message('目前該頻道沒有登入器')
            return

        login = self.login_dict[interaction.channel_id]
        if not login.is_login:
            await interaction.response.send_message('目前該頻道尚未登入BF')
            return

        return [
            app_commands.Choice(name=account.account_name,
                                value=account.account)
            for account in (await login.get_maplestory_account_list())
        ]

    @app_commands.command(name="game", description="登入遊戲")
    @app_commands.autocomplete(game_account=game_account_autocomplete)
    async def game(self, interaction: discord.Interaction, game_account: str):

        if interaction.channel_id not in self.login_dict:
            await interaction.response.send_message('目前該頻道沒有登入器')
            return

        login = self.login_dict[interaction.channel_id]
        if not login.is_login:
            await interaction.response.send_message('目前該頻道尚未登入BF')
            return
        account_model = None
        for i in (await login.get_maplestory_account_list()):
            if i.account == game_account:
                account_model = i
        if account_model is None:
            await interaction.response.send_message('! 沒找到這個帳號')
            return

        await interaction.response.send_message(f'於20s後刪除\n帳號: {account_model.account}\n密碼: {await login.get_account_otp(account=account_model)}')  # noqa: E501


async def setup(bot: commands.Bot) -> None:

    await bot.add_cog(BeanfunCog(bot), guilds=[discord.Object(id=i) for i in LIMIT_GUILD])
