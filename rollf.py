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
    start, end = today_range()

    with db() as con:
        today_row = con.execute(
            """
            SELECT value
            FROM rolls
            WHERE user_id = ?
              AND actor_type = 'user'
              AND rolled_at BETWEEN ? AND ?
            LIMIT 1
            """,
            (target.id, start, end)
        ).fetchone()

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

    if today_row:
        embed.add_field(
            name="Today",
            value=f"Today's roll: **{today_row[0]}**",
            inline=False
        )
    else:
        embed.add_field(
            name="Today",
            value="No roll yet today.",
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
        row = con.execute(
            """
            SELECT value
            FROM rolls
            WHERE user_id = ?
              AND actor_type = 'user'
              AND rolled_at BETWEEN ? AND ?
            LIMIT 1
            """,
            (interaction.user.id, start, end)
        ).fetchone()

    if row:
        value = row[0]

        now = datetime.now(TZ)
        midnight = datetime(now.year, now.month, now.day, tzinfo=TZ) + timedelta(days=1)
        remaining = max(0, int((midnight - now).total_seconds()))

        hours, remainder = divmod(remaining, 3600)
        minutes, seconds = divmod(remainder, 60)

        if remaining < 60:
            time_left = f"{seconds}s"
        elif remaining < 3600:
            time_left = f"{minutes}m"
        else:
            time_left = f"{hours}h {minutes}m"

        await interaction.response.send_message(
            f"{interaction.user.mention}\n"
            f"You already rolled **{value}** today.\n"
            f"Try again in {time_left}."
        )
        return


    value = secrets.randbelow(100) + 1

    steps = secrets.randbelow(6)  # 0–6 

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
@app_commands.describe(period="Select leaderboard period")
@app_commands.choices(period=[
    app_commands.Choice(name="Today", value="today"),
    app_commands.Choice(name="Week", value="week"),
    app_commands.Choice(name="Month", value="month"),
    app_commands.Choice(name="Year", value="year"),
    app_commands.Choice(name="All Time", value="alltime"),
])
async def leaderboards(
    interaction: discord.Interaction,
    period: app_commands.Choice[str] = None
):
    period_value = period.value if period else "today"
    now = datetime.now(TZ)

    include_bot = period_value == "today"

    start_ts = None
    end_ts = None

    # ---- PERIOD LOGIC ----
    if period_value == "today":
        start = datetime(now.year, now.month, now.day, tzinfo=TZ)
        end = start + timedelta(days=1)
        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())
        title_suffix = f"Today — {now.strftime('%B %d')}"

    elif period_value == "week":
        start = now - timedelta(days=now.weekday())
        start = datetime(start.year, start.month, start.day, tzinfo=TZ)
        end = start + timedelta(days=7)
        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())
        title_suffix = f"Week {now.isocalendar().week}"

    elif period_value == "month":
        start = datetime(now.year, now.month, 1, tzinfo=TZ)
        if now.month == 12:
            end = datetime(now.year + 1, 1, 1, tzinfo=TZ)
        else:
            end = datetime(now.year, now.month + 1, 1, tzinfo=TZ)
        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())
        title_suffix = f"{now.strftime('%B')} {now.year}"

    elif period_value == "year":
        start = datetime(now.year, 1, 1, tzinfo=TZ)
        end = datetime(now.year + 1, 1, 1, tzinfo=TZ)
        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())
        title_suffix = f"{now.year}"

    elif period_value == "alltime":
        title_suffix = "All Time"

    actor_filter = "IN ('user','bot')" if include_bot else "= 'user'"

    with db() as con:

        if period_value == "alltime":
            rows = con.execute(f"""
                SELECT COALESCE(u.username, r.username), SUM(r.value), r.user_id
                FROM rolls r
                LEFT JOIN users u ON u.user_id = r.user_id
                WHERE r.actor_type {actor_filter}
                GROUP BY r.user_id
                ORDER BY SUM(r.value) DESC
                LIMIT 10
            """).fetchall()

            ranking = con.execute(f"""
                SELECT r.user_id, SUM(r.value)
                FROM rolls r
                WHERE r.actor_type {actor_filter}
                GROUP BY r.user_id
                ORDER BY SUM(r.value) DESC
            """).fetchall()

            stats_row = con.execute(f"""
                SELECT COUNT(DISTINCT user_id), COUNT(*)
                FROM rolls
                WHERE actor_type {actor_filter}
            """).fetchone()

        else:
            aggregate = "MAX(r.value)" if period_value == "today" else "SUM(r.value)"

            rows = con.execute(f"""
                SELECT COALESCE(u.username, r.username), {aggregate}, r.user_id
                FROM rolls r
                LEFT JOIN users u ON u.user_id = r.user_id
                WHERE r.rolled_at BETWEEN ? AND ?
                  AND r.actor_type {actor_filter}
                GROUP BY r.user_id
                ORDER BY {aggregate} DESC
                LIMIT 10
            """, (start_ts, end_ts)).fetchall()

            ranking = con.execute(f"""
                SELECT r.user_id, {aggregate}
                FROM rolls r
                WHERE r.rolled_at BETWEEN ? AND ?
                  AND r.actor_type {actor_filter}
                GROUP BY r.user_id
                ORDER BY {aggregate} DESC
            """, (start_ts, end_ts)).fetchall()

            stats_row = con.execute(f"""
                SELECT COUNT(DISTINCT user_id), COUNT(*)
                FROM rolls
                WHERE rolled_at BETWEEN ? AND ?
                  AND actor_type {actor_filter}
            """, (start_ts, end_ts)).fetchone()

    embed = discord.Embed(title="Leaderboards")

    # ---- TABLE ----
    lines = []
    header = f"{'#':<3} {'USER':<16} {'SCORE':>10}"
    lines.append(header)
    lines.append("-" * len(header))

    for i, (username, score, uid) in enumerate(rows, start=1):
        name = trim(username)

        if i == 1:
            medal = " 🥇"
        elif i == 2:
            medal = " 🥈"
        elif i == 3:
            medal = " 🥉"
        else:
            medal = ""

        lines.append(f"{i:<3} {name:<16} {score:>10,}{medal}")

    block = "\n".join(lines) if rows else "No data."

    embed.add_field(
        name=title_suffix,
        value=f"```{block}```",
        inline=False
    )

    # ---- PARTICIPATION STATS ----
    players_count = stats_row[0] or 0
    rolls_count = stats_row[1] or 0

    embed.add_field(
        name="Statistics",
        value=f"Users: {players_count}\nRolls: {rolls_count}",
        inline=False
    )

    # ---- USER POSITION ----
    user_rank = None
    user_score = None

    for index, (uid, score) in enumerate(ranking, start=1):
        if uid == interaction.user.id:
            user_rank = index
            user_score = score
            break

    top_ids = [uid for _, _, uid in rows]

    if user_rank and interaction.user.id not in top_ids:
        embed.add_field(
            name="Your Position",
            value=f"#{user_rank} — {user_score:,}",
            inline=False
        )

    # ---- RESET TIMER (ONLY TODAY) ----
    if period_value == "today":
        midnight = datetime(now.year, now.month, now.day, tzinfo=TZ) + timedelta(days=1)
        remaining = max(0, int((midnight - now).total_seconds()))

        if remaining < 60:
            time_left = "0m"
        elif remaining < 3600:
            minutes = remaining // 60
            time_left = f"{minutes}m"
        else:
            hours = remaining // 3600
            time_left = f"{hours}h"

        embed.set_footer(
            text=f"Resets in {time_left} • Europe/Stockholm"
        )
    else:
        embed.set_footer(text="Europe/Stockholm")

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
