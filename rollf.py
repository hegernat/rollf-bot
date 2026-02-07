import asyncio
import sqlite3
import secrets
import time
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# ---------------- CONFIG ----------------

TZ = ZoneInfo("Europe/Stockholm")
BOT_NAME = "RollF"
DB_PATH = "bot.db"

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

ALREADY_ROLLED_MESSAGES = [
    "{user}, you've already rolled today. Rules didn’t change.",
    "{user}, one roll per day. Still.",
    "{user}, that roll already happened.",
    "{user}, try again tomorrow. Today is done.",
    "{user}, no rerolls. Ever.",
    "{user}, denied! Only once a day.",
]

ONBOARDING_TEXT = (
    "**Thanks for adding RollF!**\n\n"
    "RollF can post **one daily roll automatically**, but needs a channel to be configured.\n\n"
    "To enable daily rolls:\n"
    "• Run `/setchannel` in the channel where you want RollF to post\n"
    "• Make sure RollF is allowed to send messages in that channel\n\n"
    "Slash commands like `/roll`, `/leaderboards` and `/stats` work immediately.\n\n"
    "You can see this message again anytime with `/help`."
)

# ---------------- DB ----------------

def db():
    return sqlite3.connect(DB_PATH)

def today_range():
    now = datetime.now(TZ)
    start = datetime(now.year, now.month, now.day, tzinfo=TZ)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())

def bot_rolled_today():
    start, end = today_range()
    with db() as con:
        cur = con.execute(
            """SELECT 1 FROM rolls
               WHERE actor_type='bot'
               AND rolled_at BETWEEN ? AND ?
               LIMIT 1""",
            (start, end)
        )
        return cur.fetchone() is not None
        
def upsert_user(user_id: int, username: str):
    now = int(time.time())
    with db() as con:
        con.execute(
            """
            INSERT INTO users (user_id, username, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                username = excluded.username,
                updated_at = excluded.updated_at
            """,
            (user_id, username, now)
        )


def insert_roll(user_id, username, value, actor_type):
    with db() as con:
        con.execute(
            """INSERT INTO rolls (user_id, username, value, rolled_at, actor_type)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, username, value, int(time.time()), actor_type)
        )

def trim(name: str, max_len: int = 16) -> str:
    return name if len(name) <= max_len else name[:max_len - 1] + "…"
    
def get_user_stats(user_id: int):
    with db() as con:
        total = con.execute(
            """
            SELECT
                COUNT(*) AS rolls,
                SUM(value) AS score,
                MAX(value) AS best,
                AVG(value) AS avg
            FROM rolls
            WHERE user_id = ?
              AND actor_type = 'user'
            """,
            (user_id,)
        ).fetchone()

        last10 = con.execute(
            """
            SELECT AVG(value)
            FROM (
                SELECT value
                FROM rolls
                WHERE user_id = ?
                  AND actor_type = 'user'
                ORDER BY rolled_at DESC
                LIMIT 10
            )
            """,
            (user_id,)
        ).fetchone()[0]

        rank = con.execute(
            """
            SELECT COUNT(*) + 1
            FROM (
                SELECT user_id, SUM(value) AS score
                FROM rolls
                WHERE actor_type = 'user'
                GROUP BY user_id
            )
            WHERE score > (
                SELECT SUM(value)
                FROM rolls
                WHERE user_id = ?
                  AND actor_type = 'user'
            )
            """,
            (user_id,)
        ).fetchone()[0]

    return {
        "rolls": total[0] or 0,
        "score": total[1] or 0,
        "best": total[2] or 0,
        "avg": float(total[3]) if total[3] else 0.0,
        "avg10": float(last10) if last10 else 0.0,
        "rank": rank
    }


# ---------------- BOT SETUP ----------------

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- EVENTS ----------------

@bot.event
async def on_guild_join(guild: discord.Guild):

    with db() as con:
        row = con.execute(
            "SELECT onboarding_sent FROM guild_meta WHERE guild_id=?",
            (guild.id,)
        ).fetchone()

        if row and row[0]:
            return

    channel = None
    for ch in guild.text_channels:
        perms = ch.permissions_for(guild.me)
        if perms.view_channel and perms.send_messages:
            channel = ch
            break

    if channel is None:
        return  # No valid channel → stay silent

    try:
        await channel.send(ONBOARDING_TEXT)
        with db() as con:
            con.execute(
                "INSERT OR REPLACE INTO guild_meta (guild_id, onboarding_sent) VALUES (?, 1)",
                (guild.id,)
            )
    except discord.Forbidden:
        pass  # Shouldn't happen, but stay silent


@bot.event
async def on_ready():
    await bot.tree.sync()
    bot.loop.create_task(bot_daily_roll())
    print(f"{BOT_NAME} online & commands synced")

# ---------------- DAILY BOT ROLL ----------------

async def bot_daily_roll():
    await bot.wait_until_ready()

    while not bot.is_closed():
        now = datetime.now(TZ)

        if bot_rolled_today():
            tomorrow = (now + timedelta(days=1)).replace(hour=5, minute=55, second=0, microsecond=0)
            await asyncio.sleep((tomorrow - now).total_seconds())
            continue

        if now.hour >= 10:
            tomorrow = (now + timedelta(days=1)).replace(hour=5, minute=55, second=0, microsecond=0)
            await asyncio.sleep((tomorrow - now).total_seconds())
            continue

        if now.hour < 6:
            target = now.replace(hour=6, minute=0, second=0, microsecond=0)
            await asyncio.sleep((target - now).total_seconds())

        delay = secrets.randbelow(4 * 60 * 60)
        await asyncio.sleep(delay)

        if bot_rolled_today():
            continue

        value = secrets.randbelow(100) + 1
        insert_roll(0, BOT_NAME, value, "bot")

        with db() as con:
            rows = con.execute(
                "SELECT guild_id, channel_id FROM guild_channels"
            ).fetchall()

        for guild_id, channel_id in rows:

            channel = bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await bot.fetch_channel(channel_id)
                except discord.NotFound:
                    continue
                except discord.Forbidden:
                    try:
                        guild = bot.get_guild(guild_id)
                        if guild and guild.owner:
                            await guild.owner.send(
                                f"RollF could not access the configured channel on **{guild.name}**.\n"
                                f"Reason: missing permissions or role conflicts.\n"
                                f"Fix: give RollF explicit permissions in the selected channel "
                                f"(View Channel, Send Messages, Embed Links) and check category denies."
                            )
                    except Exception:
                        pass
                    continue
                except discord.HTTPException:
                    continue

            try:
                await channel.send(f"{BOT_NAME} rolled **{value}** 🎲")
            except discord.Forbidden:
                try:
                    guild = bot.get_guild(guild_id)
                    if guild and guild.owner:
                        await guild.owner.send(
                            f"RollF failed to send its daily roll in **{guild.name}**.\n"
                            f"Please check channel permissions."
                        )
                except Exception:
                    pass

# ---------------- COMMANDS ----------------

@bot.tree.command(name="stats")
async def stats(
    interaction: discord.Interaction,
    user: discord.User | None = None
):
    target = user or interaction.user

    stats = get_user_stats(target.id)

    if stats["rolls"] == 0:
        await interaction.response.send_message(
            "No statistics exists for this user.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"Stats for {target.name}",
        color=discord.Color.dark_gray()
    )

    embed.add_field(
        name="All-time",
        value=(
            f"Total rolls: **{stats['rolls']}**\n"
            f"Total score: **{stats['score']:,}**\n"
            f"Global rank: **#{stats['rank']}**\n"
            f"Best roll: **{stats['best']}**"
        ),
        inline=False
    )

    embed.add_field(
        name="Averages",
        value=(
            f"All-time avg: **{stats['avg']:.1f}**\n"
            f"Last 10 rolls avg: **{stats['avg10']:.1f}**"
        ),
        inline=False
    )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="help")
async def help_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "Admins only.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        ONBOARDING_TEXT,
        ephemeral=True
    )

@bot.tree.command(name="roll")
async def roll(interaction: discord.Interaction):
    start, end = today_range()

    with db() as con:
        cur = con.execute(
            """
            SELECT 1 FROM rolls
            WHERE user_id = ?
              AND actor_type = 'user'
              AND rolled_at BETWEEN ? AND ?
            """,
            (interaction.user.id, start, end)
        )
        if cur.fetchone():
            msg = random.choice(ALREADY_ROLLED_MESSAGES).format(
                user=interaction.user.mention
            )
            await interaction.response.send_message(msg)
            return

    value = secrets.randbelow(100) + 1

    steps = secrets.randbelow(6)  # 0–5

    if steps == 0:
        upsert_user(interaction.user.id, interaction.user.name)
        insert_roll(interaction.user.id, interaction.user.name, value, "user")
        await interaction.response.send_message(
            f"{interaction.user.mention} rolled **{value}** 🎲"
        )
        return

    await interaction.response.send_message(
        f"{interaction.user.mention} rolling..."
    )
    msg = await interaction.original_response()

    for _ in range(steps):
        fake = secrets.randbelow(100) + 1
        while fake == value:
            fake = secrets.randbelow(100) + 1

        await msg.edit(
            content=f"{interaction.user.mention} rolling {fake}"
        )
        await asyncio.sleep(0.35)

    upsert_user(interaction.user.id, interaction.user.name)
    insert_roll(interaction.user.id, interaction.user.name, value, "user")
    await msg.edit(
        content=f"{interaction.user.mention} rolled **{value}** 🎲"
    )

@bot.tree.command(name="leaderboards")
async def leaderboards(interaction: discord.Interaction):
    start, end = today_range()

    with db() as con:
        today = con.execute(
            """
            SELECT
                COALESCE(u.username, r.username) AS username,
                MAX(r.value) AS v
            FROM rolls r
            LEFT JOIN users u ON u.user_id = r.user_id
            WHERE r.rolled_at BETWEEN ? AND ?
              AND r.actor_type IN ('user', 'bot')
            GROUP BY r.user_id
            ORDER BY v DESC
            LIMIT 10
            """,
            (start, end)
        ).fetchall()

        alltime = con.execute(
            """
            SELECT
                COALESCE(u.username, r.username) AS username,
                SUM(r.value) AS s
            FROM rolls r
            LEFT JOIN users u ON u.user_id = r.user_id
            WHERE r.actor_type IN ('user', 'bot')
            GROUP BY r.user_id
            ORDER BY s DESC
            LIMIT 10    
            """
        ).fetchall()

    embed = discord.Embed(title="Leaderboards")

    # -------- TODAY --------
    today_lines = []
    header_today = f"{'#':<3} {'USER':<16} {'ROLL':>4}"
    today_lines.append(header_today)
    today_lines.append("-" * len(header_today))

    for i, (u, v) in enumerate(today, start=1):
        name = trim(u)
        today_lines.append(f"{i:<3} {name:<16} {v:>4}")

    today_block = (
        "\n".join(today_lines)
        if len(today) > 0
        else "No rolls today."
    )

    embed.add_field(
        name="Today — Highest Roll",
        value=f"```{today_block}```",
        inline=False
    )

    # -------- ALL TIME --------
    alltime_lines = []
    header_all = f"{'#':<3} {'USER':<16} {'TOTAL':>9}"
    alltime_lines.append(header_all)
    alltime_lines.append("-" * len(header_all))

    for i, (u, s) in enumerate(alltime, start=1):
        name = trim(u)
        alltime_lines.append(
            f"{i:<3} {name:<16} {s:>9,}"
        )

    alltime_block = (
        "\n".join(alltime_lines)
        if len(alltime) > 0
        else "No data."
    )

    embed.add_field(
        name="All Time",
        value=f"```{alltime_block}```",
        inline=False
    )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="setchannel")
@app_commands.checks.has_permissions(manage_guild=True)
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    with db() as con:
        con.execute(
            """INSERT INTO guild_channels (guild_id, channel_id, set_at)
               VALUES (?, ?, ?)
               ON CONFLICT(guild_id)
               DO UPDATE SET channel_id=excluded.channel_id, set_at=excluded.set_at""",
            (interaction.guild.id, channel.id, int(time.time()))
        )

    await interaction.response.send_message(
        f"Daily rolls will be posted in {channel.mention}",
        ephemeral=True
    )
    
# ---------------- RUN ----------------
bot.run(TOKEN)