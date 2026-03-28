import os
import asyncio
from discord.ext import commands
import discord
from utils.config import BOT_TOKEN, FEAT_APP_SERVER, API_PORT, DB_PATH

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=".", intents=intents)
bot.login_dict = {}


@bot.event
async def on_ready():
    print(f"Login: {bot.user} Success.")


@bot.command()
async def load(ctx, extension):
    await bot.load_extension(f"cogs.{extension}")
    await ctx.send(f"Loaded {extension} done.")


@bot.command()
async def unload(ctx, extension):
    await bot.unload_extension(f"cogs.{extension}")
    await ctx.send(f"UnLoaded {extension} done.")


@bot.command()
async def reload(ctx, extension):
    await bot.reload_extension(f"cogs.{extension}")
    await ctx.send(f"ReLoaded {extension} done.")


async def load_extensions():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            await bot.load_extension(f"cogs.{filename[:-3]}")


async def main():
    if BOT_TOKEN is None:
        raise ValueError("Not found BOT_TOKEN")

    async with bot:
        if FEAT_APP_SERVER:
            from database.token_db import TokenDatabase
            from api.server import create_api_app
            from aiohttp import web

            db = TokenDatabase(DB_PATH)
            await db.init()
            bot.token_db = db

            app = create_api_app(bot, db)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", API_PORT)
            await site.start()
            print(f"API server started on port {API_PORT}")

        await load_extensions()
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
