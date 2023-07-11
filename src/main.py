import os
import asyncio
from discord.ext import commands
import discord
from utils.config import BOT_TOKEN

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=".", intents=intents)


@bot.event
async def on_ready():
    print(f"Login: {bot.user} Success.")


# load cog file


@bot.command()
async def load(ctx, extension):
    await bot.load_extension(f"cogs.{extension}")
    await ctx.send(f"Loaded {extension} done.")


# unload cog


@bot.command()
async def unload(ctx, extension):
    await bot.unload_extension(f"cogs.{extension}")
    await ctx.send(f"UnLoaded {extension} done.")


# reload cog file.


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
        await load_extensions()
        await bot.start(BOT_TOKEN)


# 確定執行此py檔才會執行
if __name__ == "__main__":
    asyncio.run(main())
