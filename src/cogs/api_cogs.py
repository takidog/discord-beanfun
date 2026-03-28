import datetime
from typing import Any, Coroutine, List

import discord
from discord import app_commands
from discord.ext import commands

from utils.config import LIMIT_GUILD

EXPIRY_OPTIONS = {
    "-1": ("永久", None),
    "604800": ("7 天", 7 * 24 * 3600),
    "2592000": ("30 天", 30 * 24 * 3600),
    "5184000": ("60 天", 60 * 24 * 3600),
    "7776000": ("90 天", 90 * 24 * 3600),
}


class ExpirySelect(discord.ui.Select):
    def __init__(self, app_name: str):
        self.app_name = app_name
        options = [
            discord.SelectOption(label="永久", value="-1", description="Token 永不過期"),
            discord.SelectOption(label="7 天", value="604800"),
            discord.SelectOption(label="30 天", value="2592000"),
            discord.SelectOption(label="60 天", value="5184000"),
            discord.SelectOption(label="90 天", value="7776000"),
        ]
        super().__init__(
            placeholder="選擇 Token 過期時間",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        label, expires_in = EXPIRY_OPTIONS[selected]

        db = interaction.client.token_db
        channel = interaction.channel

        token = await db.create_token(
            app_name=self.app_name,
            channel_id=channel.id,
            channel_name=getattr(channel, "name", str(channel.id)),
            discord_user_id=interaction.user.id,
            discord_username=str(interaction.user),
            expires_in_seconds=expires_in,
        )

        expiry_text = label if expires_in is None else f"{label}後到期"

        await interaction.response.edit_message(
            content=(
                f"Token 已建立\n"
                f"**應用程式：** {self.app_name}\n"
                f"**過期時間：** {expiry_text}\n"
                f"**Token：** ||{token}||\n\n"
                f"請洽架設管理員取得 API endpoint 位置\n"
                f"此 Token 僅顯示一次，請妥善保存"
            ),
            view=None,
        )


class ExpiryView(discord.ui.View):
    def __init__(self, app_name: str):
        super().__init__(timeout=120)
        self.add_item(ExpirySelect(app_name))


class RegisterAppModal(discord.ui.Modal, title="註冊應用程式"):
    app_name_input = discord.ui.TextInput(
        label="應用程式名稱",
        placeholder="例如：my-launcher",
        min_length=1,
        max_length=64,
    )

    async def on_submit(self, interaction: discord.Interaction):
        app_name = self.app_name_input.value.strip()
        view = ExpiryView(app_name)
        await interaction.response.send_message(
            f"為 **{app_name}** 選擇 Token 過期時間：",
            view=view,
            ephemeral=True,
        )


class RevokeSelect(discord.ui.Select):
    def __init__(self, tokens):
        self._tokens = {str(t.id): t for t in tokens}
        options = []
        for t in tokens:
            exp = "永久" if t.expires_at is None else datetime.datetime.fromtimestamp(
                t.expires_at
            ).strftime("%Y-%m-%d")
            options.append(
                discord.SelectOption(
                    label=t.app_name,
                    value=str(t.id),
                    description=f"到期: {exp}",
                )
            )
        super().__init__(
            placeholder="選擇要撤銷的應用程式",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        token_id = int(self.values[0])
        record = self._tokens.get(self.values[0])
        db = interaction.client.token_db

        success = await db.revoke_token(token_id)
        if success:
            await interaction.response.edit_message(
                content=f"已撤銷應用程式 **{record.app_name}** 的 Token",
                view=None,
            )
        else:
            await interaction.response.edit_message(
                content="撤銷失敗，Token 可能已經被撤銷",
                view=None,
            )


class RevokeView(discord.ui.View):
    def __init__(self, tokens):
        super().__init__(timeout=120)
        self.add_item(RevokeSelect(tokens))


class ApiCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> Coroutine[Any, Any, None]:
        return await super().cog_load()

    @app_commands.command(name="register-app", description="註冊外部應用程式，取得 API Token")
    async def register_app(self, interaction: discord.Interaction):
        modal = RegisterAppModal()
        await interaction.response.send_modal(modal)

    @app_commands.command(name="list-apps", description="列出本頻道已註冊的應用程式")
    async def list_apps(self, interaction: discord.Interaction):
        db = self.bot.token_db
        tokens = await db.list_tokens(interaction.channel_id)

        if not tokens:
            await interaction.response.send_message(
                "本頻道沒有已註冊的應用程式", ephemeral=True
            )
            return

        lines = []
        for t in tokens:
            exp = "永久" if t.expires_at is None else datetime.datetime.fromtimestamp(
                t.expires_at
            ).strftime("%Y-%m-%d %H:%M")
            status = "有效"
            if t.expires_at is not None:
                import time
                if time.time() > t.expires_at:
                    status = "已過期"
            lines.append(
                f"- **{t.app_name}** | 建立者: {t.discord_username} | "
                f"到期: {exp} | 狀態: {status}"
            )

        await interaction.response.send_message(
            "**已註冊的應用程式：**\n" + "\n".join(lines),
            ephemeral=True,
        )

    @app_commands.command(name="revoke-app", description="撤銷應用程式的 API Token")
    async def revoke_app(self, interaction: discord.Interaction):
        db = self.bot.token_db
        tokens = await db.list_user_tokens(
            interaction.channel_id, interaction.user.id
        )

        if not tokens:
            await interaction.response.send_message(
                "你在本頻道沒有可撤銷的應用程式", ephemeral=True
            )
            return

        view = RevokeView(tokens)
        await interaction.response.send_message(
            "選擇要撤銷的應用程式：",
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    if not getattr(bot, "token_db", None):
        return
    await bot.add_cog(
        ApiCog(bot), guilds=[discord.Object(id=i) for i in LIMIT_GUILD]
    )
