# -----------------------------------------
# RollF – Minimal daily roll Discord bot
# Copyright (c) 2026 hegernat
# Licensed under the MIT License
#
# Source: https://github.com/hegernat/rollf-bot
# -----------------------------------------

import threading
import aiohttp
import asyncio
import sqlite3
import secrets
import time
import csv
import io
import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont

# ---------------- CONFIG ----------------

TZ = ZoneInfo("Europe/Stockholm")
BOT_NAME = "RollF"
DB_PATH = "bot.db"

BOTLIST_COMMANDS = [
    {"command": "roll", "description": "Roll your daily number (1–100)"},
    {"command": "leaderboards", "description": "View rankings for different periods"},
    {"command": "stats", "description": "View detailed statistics"},
    {"command": "setchannel", "description": "Set the channel for daily bot rolls"},
    {"command": "help", "description": "Show setup instructions"}
]

load_dotenv()

DAILY_ROLL_TASK = None

# ---------------- ADMIN ----------------

ADMIN_MODE = os.getenv("ADMIN_MODE") == "true"
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
ADMIN_GUILD_ID = int(os.getenv("ADMIN_GUILD_ID", "0"))
TOKEN = os.getenv("DISCORD_TOKEN")
BOTLIST_TOKEN = os.getenv("BOTLIST_TOKEN")
TOPGG_TOKEN = os.getenv("TOPGG_TOKEN")

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

async def post_bot_stats():

    guild_count = len(bot.guilds)
    bot_id = bot.user.id

    async with aiohttp.ClientSession() as session:

        if BOTLIST_TOKEN:
            try:
                await session.post(
                    f"https://discordbotlist.com/api/v1/bots/{bot_id}/stats",
                    json={"guilds": guild_count},
                    headers={"Authorization": BOTLIST_TOKEN},
                    timeout=aiohttp.ClientTimeout(total=10)
                )
            except Exception as e:
                print("Botlist stats failed:", e)

        if TOPGG_TOKEN:
            try:
                await session.post(
                    f"https://top.gg/api/bots/{bot_id}/stats",
                    json={"server_count": guild_count},
                    headers={"Authorization": TOPGG_TOKEN},
                    timeout=aiohttp.ClientTimeout(total=10)
                )
            except Exception as e:
                print("Top.gg stats failed:", e)

async def post_botlist_commands():

    if not BOTLIST_TOKEN:
        return

    bot_id = bot.user.id

    async with aiohttp.ClientSession() as session:
        try:
            await session.post(
                f"https://discordbotlist.com/api/v1/bots/{bot_id}/commands",
                json=BOTLIST_COMMANDS,
                headers={"Authorization": BOTLIST_TOKEN},
                timeout=aiohttp.ClientTimeout(total=10)
            )
        except Exception as e:
            print("Botlist commands update failed:", e)

def ensure_schema():

    with db() as con:

        cols = con.execute("PRAGMA table_info(rolls)").fetchall()
        names = {c[1] for c in cols}

        if "roll_date" not in names:
            con.execute("ALTER TABLE rolls ADD COLUMN roll_date TEXT")

        con.execute("""
        UPDATE rolls
        SET roll_date = date(rolled_at, 'unixepoch')
        WHERE roll_date IS NULL
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS daily_scores (
            user_id INTEGER,
            roll_date TEXT,
            score INTEGER NOT NULL,
            rolls INTEGER NOT NULL,
            PRIMARY KEY(user_id, roll_date)
        )
        """)

        count = con.execute(
            "SELECT COUNT(*) FROM daily_scores"
        ).fetchone()[0]

        if count == 0:
            con.execute("""
            INSERT INTO daily_scores (user_id, roll_date, score, rolls)
            SELECT
                user_id,
                roll_date,
                SUM(value),
                COUNT(*)
            FROM rolls
            WHERE actor_type = 'user'
              AND roll_date IS NOT NULL
            GROUP BY user_id, roll_date
            """)

_local = threading.local()

def db():
    con = getattr(_local, "con", None)

    if con is None:
        con = sqlite3.connect(
            DB_PATH,
            timeout=30,
            isolation_level=None
        )
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA temp_store=MEMORY")
        con.execute("PRAGMA foreign_keys=ON")
        _local.con = con

    return con

def ensure_indexes():
    with db() as con:

        con.execute("""
        CREATE INDEX IF NOT EXISTS idx_guild_channels_guild
        ON guild_channels(guild_id)
        """)

        con.execute("""
        CREATE INDEX IF NOT EXISTS idx_guild_channels_channel
        ON guild_channels(channel_id)
        """)

        con.execute("""
        CREATE INDEX IF NOT EXISTS idx_rolls_actor_date
        ON rolls(actor_type, roll_date)
        """)

        con.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_one_roll_per_day
        ON rolls(user_id, roll_date)
        WHERE actor_type='user'
        """)

        con.execute("""
        CREATE INDEX IF NOT EXISTS idx_daily_scores_date
        ON daily_scores(roll_date)
        """)

        con.execute("""
        CREATE INDEX IF NOT EXISTS idx_rolls_actor_time_user
        ON rolls(actor_type, rolled_at, user_id)
        """)

        con.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_scores_score
        ON user_scores(score DESC)
        """)

        con.execute("""
        CREATE INDEX IF NOT EXISTS idx_rolls_user_time
        ON rolls(user_id, rolled_at)
        """)

        con.execute("""
        CREATE INDEX IF NOT EXISTS idx_rolls_time
        ON rolls(rolled_at)
        """)

        con.execute("""
        CREATE INDEX IF NOT EXISTS idx_rolls_user_period
        ON rolls(rolled_at, user_id)
        WHERE actor_type='user'
        """)

        con.execute("""
        CREATE INDEX IF NOT EXISTS idx_rolls_user_date
        ON rolls(user_id, roll_date)
        WHERE actor_type='user'
        """)

        con.execute("""
        CREATE TABLE IF NOT EXISTS user_scores (
            user_id INTEGER PRIMARY KEY,
            score INTEGER NOT NULL DEFAULT 0,
            rolls INTEGER NOT NULL DEFAULT 0,
            best INTEGER NOT NULL DEFAULT 0
        )
        """)

        count = con.execute("SELECT COUNT(*) FROM user_scores").fetchone()[0]

        if count == 0:
            con.execute("""
            INSERT INTO user_scores (user_id, score, rolls, best)
            SELECT
                user_id,
                SUM(value),
                COUNT(*),
                MAX(value)
            FROM rolls
            WHERE actor_type = 'user'
            GROUP BY user_id
            """)

            print("Backfilled user_scores from rolls table")

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

    ts = int(time.time())
    roll_date = datetime.fromtimestamp(ts, TZ).date().isoformat()

    with db() as con:

        try:
            con.execute(
                """INSERT INTO rolls (user_id, username, value, rolled_at, actor_type, roll_date)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, username, value, ts, actor_type, roll_date)
            )
        except sqlite3.IntegrityError:
            return False

        if actor_type == 'user':
            con.execute("""
            INSERT INTO user_scores (user_id, score, rolls, best)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                score = score + excluded.score,
                rolls = rolls + 1,
                best = MAX(best, excluded.best)
            """, (user_id, value, value))

            con.execute("""
            INSERT INTO daily_scores (user_id, roll_date, score, rolls)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(user_id, roll_date) DO UPDATE SET
                score = score + excluded.score,
                rolls = rolls + 1
            """, (user_id, roll_date, value))

    return True

def trim(name, max_len=16):
    return name[:max_len-1] + "…" if len(name) > max_len else name
    
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
            FROM user_scores
            WHERE score >
            (
                SELECT score
                FROM user_scores
                WHERE user_id = ?
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

def calculate_streaks(user_id: int):

    with db() as con:
        rows = con.execute("""
            SELECT DISTINCT roll_date
            FROM rolls
            WHERE user_id = ?
              AND actor_type = 'user'
            ORDER BY roll_date
        """, (user_id,)).fetchall()

    if not rows:
        return 0, 0

    dates = [datetime.fromisoformat(r[0]).date() for r in rows if r[0]]

    best = 0
    current_run = 0
    prev_date = None

    for d in dates:

        if prev_date is None:
            current_run = 1

        elif d == prev_date + timedelta(days=1):
            current_run += 1

        else:
            current_run = 1

        best = max(best, current_run)
        prev_date = d

    today = datetime.now(TZ).date()

    date_set = set(dates)

    if today not in date_set:
        current = 0
    else:
        current = 1
        check_day = today

        while True:
            check_day -= timedelta(days=1)

            if check_day in date_set:
                current += 1
            else:
                break

    return current, best

def get_period_stats(user_id: int, start_ts: int, end_ts: int):
    with db() as con:
        total = con.execute("""
            SELECT COUNT(*), SUM(value), MAX(value)
            FROM rolls
            WHERE user_id = ?
              AND actor_type = 'user'
              AND rolled_at BETWEEN ? AND ?
        """, (user_id, start_ts, end_ts)).fetchone()

        rank = con.execute("""
            SELECT COUNT(*) + 1
            FROM (
                SELECT user_id, SUM(value) AS score
                FROM rolls
                WHERE actor_type = 'user'
                  AND rolled_at BETWEEN ? AND ?
                GROUP BY user_id
            )
            WHERE score > (
                SELECT SUM(value)
                FROM rolls
                WHERE user_id = ?
                  AND actor_type = 'user'
                  AND rolled_at BETWEEN ? AND ?
            )
        """, (start_ts, end_ts, user_id, start_ts, end_ts)).fetchone()[0]

    return {
        "rolls": total[0] or 0,
        "score": total[1] or 0,
        "best": total[2] or 0,
        "rank": rank
    }

def format_score(n: int) -> str:
    if n >= 1000:
        truncated = (n // 100) / 10
        return f"{truncated:.1f}k"
    return str(n)

def render_leaderboard_png(title, rows, users_count=0, rolls_count=0):

    import io

    width = 600

    top_padding = 20
    header_y = 120
    row_height = 48

    height = 750

    img = Image.new(
        "RGB",
        (width, height),
        (35, 39, 42)
    )

    draw = ImageDraw.Draw(img)

    title_font = ImageFont.truetype(
        "assets/fonts/JetBrainsMono-Regular.ttf",
        36
    )

    body_font = ImageFont.truetype(
        "assets/fonts/JetBrainsMono-Regular.ttf",
        28
    )

    RANK_X = 20
    USER_X = 95
    SCORE_RIGHT = 550

    draw.text(
        (20, top_padding),
        title,
        fill=(255, 255, 255),
        font=title_font
    )

    draw.text(
        (RANK_X, header_y),
        "#",
        fill=(180, 180, 180),
        font=body_font
    )

    draw.text(
        (USER_X, header_y),
        "USER",
        fill=(180, 180, 180),
        font=body_font
    )

    draw.text(
        (470, header_y),
        "SCORE",
        fill=(180, 180, 180),
        font=body_font
    )

    draw.line(
        (20, header_y + 35, 580, header_y + 35),
        fill=(90, 90, 90),
        width=2
    )

    y = header_y + 50

    for pos, (username, score, uid) in enumerate(rows, start=1):

        # Zebra rows

        if pos % 2 == 0:
            draw.rectangle(
                (
                    10,
                    y - 4,
                    590,
                    y + 34
                ),
                fill=(42, 45, 50)
            )

        # Rank

        draw.text(
            (RANK_X, y),
            str(pos),
            fill=(255, 255, 255),
            font=body_font
        )

        # Username

        draw.text(
            (USER_X, y),
            trim(username, 18),
            fill=(255, 255, 255),
            font=body_font
        )

        # Score

        if score == "—":
            score_text = "—"
        else:
            score_text = format_score(score)

        bbox = draw.textbbox(
            (0, 0),
            score_text,
            font=body_font
        )

        score_width = bbox[2] - bbox[0]

        draw.text(
            (SCORE_RIGHT - score_width, y),
            score_text,
            fill=(255, 255, 255),
            font=body_font
        )

        y += row_height

    stats_font = ImageFont.truetype(
        "assets/fonts/JetBrainsMono-Regular.ttf",
        24
    )

    draw.text(
        (20, 720),
        f"Users: {users_count:,}".replace(",", " "),
        fill=(180, 180, 180),
        font=stats_font
    )

    draw.text(
        (350, 720),
        f"Rolls: {rolls_count:,}".replace(",", " "),
        fill=(180, 180, 180),
        font=stats_font
    )

    buffer = io.BytesIO()

    img.save(
        buffer,
        format="PNG"
    )

    buffer.seek(0)

    return buffer

# ---------------- BOT SETUP ----------------

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="rollf_", intents=intents)

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
        return

    try:
        await channel.send(ONBOARDING_TEXT)
        with db() as con:
            con.execute(
                "INSERT OR REPLACE INTO guild_meta (guild_id, onboarding_sent) VALUES (?, 1)",
                (guild.id,)
            )
    except discord.Forbidden:
        pass

    await post_bot_stats()

@bot.event
async def on_guild_remove(guild: discord.Guild):
    with db() as con:
        con.execute("DELETE FROM guild_channels WHERE guild_id = ?", (guild.id,))
        con.execute("DELETE FROM guild_meta WHERE guild_id = ?", (guild.id,))
    
    await post_bot_stats()

@bot.event
async def on_ready():
    global DAILY_ROLL_TASK

    ensure_schema()
    ensure_indexes()
    
    await post_botlist_commands()
    await post_bot_stats()

    print(f"{BOT_NAME} logging in...")

    # -------- Global command sync --------
    try:
        await bot.tree.sync()
        print("Global commands synced.")
    except Exception as e:
        print("Global sync failed:", e)

    # -------- Admin guild sync (safe) --------
    if ADMIN_MODE and ADMIN_GUILD_ID:
        guild_obj = bot.get_guild(ADMIN_GUILD_ID)

        if guild_obj:
            try:
                await bot.tree.sync(guild=guild_obj)
                print("Admin guild commands synced.")
            except discord.Forbidden:
                print("Admin guild sync failed: Missing Access")
            except Exception as e:
                print("Admin guild sync error:", e)
        else:
            print("Admin guild not found in bot.guilds")

    if not ADMIN_MODE:
        print("Admin mode disabled.")

    # -------- Cleanup stale guilds --------
    current_ids = {g.id for g in bot.guilds}

    with db() as con:
        db_guilds = con.execute("""
            SELECT guild_id FROM guild_channels
            UNION
            SELECT guild_id FROM guild_meta
        """).fetchall()

        cleaned = 0

        for (gid,) in db_guilds:
            if gid not in current_ids:
                con.execute("DELETE FROM guild_channels WHERE guild_id = ?", (gid,))
                con.execute("DELETE FROM guild_meta WHERE guild_id = ?", (gid,))
                cleaned += 1

    if cleaned > 0:
        print(f"Cleaned {cleaned} stale guild entries")

    # -------- Start daily roll task --------
    if DAILY_ROLL_TASK is None or DAILY_ROLL_TASK.done():
        DAILY_ROLL_TASK = asyncio.create_task(bot_daily_roll())

    print(f"{BOT_NAME} online & ready.")

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

@bot.tree.command(
    name="stats",
    description="View detailed statistics for yourself or another user"
)
async def stats(
    interaction: discord.Interaction,
    user: discord.User | None = None
):
    target = user or interaction.user
    stats = get_user_stats(target.id)
    start, end = today_range()

    week_start = now = datetime.now(TZ)
    week_start = week_start - timedelta(days=week_start.weekday())
    week_start = datetime(week_start.year, week_start.month, week_start.day, tzinfo=TZ)
    week_end = week_start + timedelta(days=7)

    month_start = datetime(now.year, now.month, 1, tzinfo=TZ)
    if now.month == 12:
        month_end = datetime(now.year + 1, 1, 1, tzinfo=TZ)
    else:
        month_end = datetime(now.year, now.month + 1, 1, tzinfo=TZ)

    week_stats = get_period_stats(target.id, int(week_start.timestamp()), int(week_end.timestamp()))
    month_stats = get_period_stats(target.id, int(month_start.timestamp()), int(month_end.timestamp()))
    current_streak, best_streak = calculate_streaks(target.id)

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

    today_rank = None

    if today_row:
        with db() as con:
            ranking_today = con.execute("""
                SELECT user_id, MAX(value) AS score
                FROM rolls
                WHERE actor_type = 'user'
                  AND rolled_at BETWEEN ? AND ?
                GROUP BY user_id
                ORDER BY score DESC
            """, (start, end)).fetchall()

        for index, (uid, _) in enumerate(ranking_today, start=1):
            if uid == target.id:
                today_rank = index
                break

    if stats["rolls"] == 0:
        await interaction.response.send_message(
            "No statistics exists for this user.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"{target.name} Statistics",
        color=discord.Color.dark_gray()
    )

    embed.set_thumbnail(url=target.display_avatar.url)

    # Row 1
    if today_row:
        today_value = (
            f"Roll: {today_row[0]}\n"
            f"Rank: #{today_rank}" if today_rank else
            f"Roll: {today_row[0]}"
        )
    else:
        today_value = "No roll yet."

    embed.add_field(
        name="Today",
        value=today_value,
        inline=True
    )

    embed.add_field(
        name="Streaks",
        value=(
            f"Current: {current_streak}d\n"
            f"Best: {best_streak}d"
        ),
        inline=True
    )

    # Row 2
    embed.add_field(
        name="Averages",
        value=(
            f"All-time: {stats['avg']:.1f}\n"
            f"Last 10: {stats['avg10']:.1f}"
        ),
        inline=True
    )

    embed.add_field(
        name="This Week",
        value=(
            f"Rolls: {week_stats['rolls']}\n"
            f"Score: {week_stats['score']:,}\n"
            f"Rank: #{week_stats['rank']}\n"
            f"Best: {week_stats['best']}"
        ),
        inline=True
    )

    # Row 3
    embed.add_field(
        name="This Month",
        value=(
            f"Rolls: {month_stats['rolls']}\n"
            f"Score: {month_stats['score']:,}\n"
            f"Rank: #{month_stats['rank']}\n"
            f"Best: {month_stats['best']}"
        ),
        inline=True
    )

    embed.add_field(
        name="All-time",
        value=(
            f"Rolls: {stats['rolls']}\n"
            f"Score: {stats['score']:,}\n"
            f"Rank: #{stats['rank']}\n"
            f"Best: {stats['best']}"
        ),
        inline=True
    )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(
    name="help",
    description="Help and setup instructions"
)
async def help_cmd(interaction: discord.Interaction):

    embed = discord.Embed(
        title="RollF",
        description=(
            "**Official Discord Server**\n"
            "https://discord.gg/Jp58N2Sr5b\n\n"
            "**Getting Started**\n"
            "RollF can post one daily roll automatically, "
            "but needs a channel to be configured first.\n\n"
            "**To enable daily rolls:**\n"
            "• Run `/setchannel`\n"
            "• Choose the channel where RollF should post\n"
            "• Make sure RollF has permission to send messages\n\n"
            "**Available commands:**\n"
            "• `/roll` — Roll your daily number\n"
            "• `/leaderboards` — View rankings\n"
            "• `/stats` — View detailed statistics\n"
            "• `/setchannel` — Configure daily rolls"
        ),
        color=discord.Color.dark_grey()
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )

@bot.tree.command(
    name="roll",
    description="Roll a number between 1 and 100 (once per day)"
)
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

        if remaining < 3600:
            # under 1h → ceil minutes
            minutes = -(-remaining // 60)
            time_left = f"{minutes}m"

        else:
            hours = remaining // 3600
            minutes = -(- (remaining % 3600) // 60)

            if minutes == 60:
                hours += 1
                minutes = 0

            if minutes == 0:
                time_left = f"{hours}h"
            else:
                time_left = f"{hours}h {minutes}m"

        await interaction.response.send_message(
            f"{interaction.user.mention}\n"
            f"You already rolled **{value}** today.\n"
            f"Try again in {time_left}."
        )
        return

    value = secrets.randbelow(100) + 1

    now = datetime.now(TZ)

    april_fools = (
        now.month == 4 and
        now.day == 1
    )

    if april_fools:
        steps = 10 + secrets.randbelow(11)
        print("!!! APRIL FOOLS ACTIVE !!!")
    else:
        steps = secrets.randbelow(6)

    if steps == 0:
        upsert_user(interaction.user.id, interaction.user.name)
        success = insert_roll(interaction.user.id, interaction.user.name, value, "user")

        if not success:
            await interaction.response.send_message(
                "You already rolled today.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"{interaction.user.mention} rolled **{value}** 🎲"
        )
        return

    await interaction.response.send_message(
        f"{interaction.user.mention} rolling..."
    )
    msg = await interaction.original_response()

    for _ in range(steps):

        if april_fools:                                             # April Fools' Day event
            fake = secrets.randbelow(900_000_000) + 100_000_000     # Displays fake massive roll values on April 1st.
        else:                                                       # Real values are still stored in the database.
            fake = secrets.randbelow(100) + 1

            while fake == value:
                fake = secrets.randbelow(100) + 1

        await msg.edit(
            content=f"{interaction.user.mention} rolling {fake:,}"
        )

        if april_fools:
            await asyncio.sleep(0.2)
        else:
            await asyncio.sleep(0.5)

    upsert_user(interaction.user.id, interaction.user.name)
    success = insert_roll(interaction.user.id, interaction.user.name, value, "user")

    if not success:
        await msg.edit(
            content=f"{interaction.user.mention}\nYou already rolled today."
        )
        return

    current_streak, _ = calculate_streaks(interaction.user.id)
    milestones = {10, 25, 50, 100, 250, 500, 1000}

    display_value = value

    if april_fools:
        display_value = (
            value * 10_000_000
            + secrets.randbelow(90_000_000)
        )

    if current_streak in milestones:
        await msg.edit(
            content=(
                f"{interaction.user.mention} rolled **{display_value:,}** 🎲\n"
                f"🔥 {current_streak}-day streak achieved."
            )
        )
    else:
        if value == 100:
            await msg.edit(
                content=f"{interaction.user.mention} rolled 💯 🎲"
            )
        else:
            await msg.edit(
                content=f"{interaction.user.mention} rolled **{display_value:,}** 🎲"
            )

@bot.tree.command(
    name="leaderboards",
    description="View leaderboards for different periods"
)
@app_commands.describe(period="Select leaderboard period")
@app_commands.choices(period=[
    app_commands.Choice(name="Today", value="today"),
    app_commands.Choice(name="Week", value="week"),
    app_commands.Choice(name="Month", value="month"),
    app_commands.Choice(name="Year", value="year"),
    app_commands.Choice(name="All Time", value="alltime"),
    app_commands.Choice(name="Streak", value="streak"),
])
async def leaderboards(
    interaction: discord.Interaction,
    period: app_commands.Choice[str] = None
):
    period_value = period.value if period else "today"

    now = datetime.now(TZ)

    rows = []
    ranking = []
    stats_row = (0, 0)

    # =========================
    # STREAK LEADERBOARD
    # =========================
    if period_value == "streak":

        with db() as con:
            all_dates = con.execute("""
                SELECT r.user_id, r.roll_date, COALESCE(u.username, r.username) as username
                FROM rolls r
                LEFT JOIN users u ON u.user_id = r.user_id
                WHERE r.actor_type = 'user' AND r.roll_date IS NOT NULL
                GROUP BY r.user_id, r.roll_date
                ORDER BY r.user_id, r.roll_date
            """).fetchall()

        user_dates = {}
        user_names = {}

        for uid, roll_date, username in all_dates:
            if uid not in user_dates:
                user_dates[uid] = set()
                user_names[uid] = username
            user_dates[uid].add(roll_date)

        # Beräkna best streak per användare
        streak_data = []

        for uid, date_set in user_dates.items():
            dates = sorted(datetime.fromisoformat(d).date() for d in date_set)
            best = 1
            current_run = 1

            for i in range(1, len(dates)):
                if dates[i] == dates[i - 1] + timedelta(days=1):
                    current_run += 1
                    best = max(best, current_run)
                else:
                    current_run = 1

            if best >= 2:
                streak_data.append((uid, best, user_names[uid]))

        streak_data.sort(key=lambda x: x[1], reverse=True)

        for uid, best, username in streak_data:
            rows.append((username, best, uid))
            ranking.append((uid, best))

        rows = rows[:10]

        title_suffix = "Longest Streaks"
        stats_row = (len(streak_data), 0)

    # =========================
    # NORMAL PERIOD LEADERBOARDS
    # =========================
    else:

        start_ts = None
        end_ts = None

        if period_value == "today":
            start = datetime(now.year, now.month, now.day, tzinfo=TZ)
            end = start + timedelta(days=1)

            start_ts = int(start.timestamp())
            end_ts = int(end.timestamp())

            start_date = start.date().isoformat()
            end_date = end.date().isoformat()

            title_suffix = f"Today — {now.strftime('%B %d')}"

        elif period_value == "week":
            start = now - timedelta(days=now.weekday())
            start = datetime(start.year, start.month, start.day, tzinfo=TZ)
            end = start + timedelta(days=7)

            start_ts = int(start.timestamp())
            end_ts = int(end.timestamp())

            start_date = start.date().isoformat()
            end_date = end.date().isoformat()

            title_suffix = f"Week {now.isocalendar().week}"

        elif period_value == "month":
            start = datetime(now.year, now.month, 1, tzinfo=TZ)

            if now.month == 12:
                end = datetime(now.year + 1, 1, 1, tzinfo=TZ)
            else:
                end = datetime(now.year, now.month + 1, 1, tzinfo=TZ)

            start_ts = int(start.timestamp())
            end_ts = int(end.timestamp())

            start_date = start.date().isoformat()
            end_date = end.date().isoformat()

            title_suffix = now.strftime("%B")

        elif period_value == "year":
            start = datetime(now.year, 1, 1, tzinfo=TZ)
            end = datetime(now.year + 1, 1, 1, tzinfo=TZ)

            start_ts = int(start.timestamp())
            end_ts = int(end.timestamp())

            start_date = start.date().isoformat()
            end_date = end.date().isoformat()

            title_suffix = f"{now.year}"

        elif period_value == "alltime":
            title_suffix = "All Time"

        with db() as con:

            if period_value == "alltime":

                rows = con.execute("""
                    SELECT
                        COALESCE(u.username, 'Unknown'),
                        s.score,
                        s.user_id
                    FROM user_scores s
                    LEFT JOIN users u ON u.user_id = s.user_id
                    ORDER BY s.score DESC
                    LIMIT 10
                """).fetchall()

                ranking = con.execute("""
                    SELECT user_id, score
                    FROM user_scores
                    ORDER BY score DESC
                    LIMIT 100
                """).fetchall()

                stats_row = con.execute("""
                    SELECT COUNT(DISTINCT user_id), COUNT(*)
                    FROM rolls
                    WHERE actor_type = 'user'
                """).fetchone()

            else:

                rows = con.execute("""
                    SELECT COALESCE(u.username, 'Unknown'), SUM(d.score), d.user_id
                    FROM daily_scores d
                    LEFT JOIN users u ON u.user_id = d.user_id
                    WHERE d.roll_date BETWEEN ? AND ?
                    GROUP BY d.user_id
                    ORDER BY SUM(d.score) DESC
                    LIMIT 10
                """, (start_date, end_date)).fetchall()

                ranking = con.execute("""
                    SELECT d.user_id,
                           COALESCE(u.username, 'Unknown') AS username,
                           SUM(d.score) AS score
                    FROM daily_scores d
                    LEFT JOIN users u ON u.user_id = d.user_id
                    WHERE d.roll_date BETWEEN ? AND ?
                    GROUP BY d.user_id
                    ORDER BY score DESC
                    LIMIT 100
                """, (start_date, end_date)).fetchall()

                stats_row = con.execute("""
                    SELECT COUNT(DISTINCT user_id), COUNT(*)
                    FROM rolls
                    WHERE rolled_at BETWEEN ? AND ?
                      AND actor_type = 'user'
                """, (start_ts, end_ts)).fetchone()

    # =========================
    # RENDER (COMMON)
    # =========================

    while len(rows) < 10:
        rows.append(("—", "—", 0))

    players_count = stats_row[0] or 0
    rolls_count = stats_row[1] or 0

    png = render_leaderboard_png(
        title_suffix,
        rows,
        players_count,
        rolls_count
    )

    file = discord.File(
        png,
        filename="leaderboard.png"
    )

    embed = discord.Embed(
       color=discord.Color.dark_grey()
    )

    embed.set_image(
        url="attachment://leaderboard.png"
    )

    user_rank = None
    user_score = None

    if user_rank is None:
        with db() as con:
            user_score = con.execute(
                "SELECT score FROM user_scores WHERE user_id = ?",
                (interaction.user.id,)
            ).fetchone()

        if user_score:
            user_score = user_score[0]

    for index, row in enumerate(ranking, start=1):

        uid = row[0]
        score = row[-1]

        if uid == interaction.user.id:
            user_rank = index
            user_score = score
            break

    delta = None

    if user_rank and user_rank > 1 and user_rank - 2 < len(ranking):
        above_row = ranking[user_rank - 2]
        above_score = above_row[-1]
        delta = above_score - user_score

    top_ids = [uid for _, _, uid in rows]

    if user_rank and interaction.user.id not in top_ids:
        if delta is not None:
            text = f"#{user_rank} — {user_score:,}\n↥ {delta:,} to #{user_rank-1}"
        else:
            text = f"#{user_rank} — {user_score:,}"

        embed.add_field(
            name="Your Position",
            value=text,
            inline=False
        )

    # =========================
    # RESET TIMER
    # =========================

    reset_text = "Europe/Stockholm (CET/CEST)"

    if period_value in ("today", "week", "month"):
        if period_value == "today":
            reset_point = datetime(now.year, now.month, now.day, tzinfo=TZ) + timedelta(days=1)

        elif period_value == "week":
            start = now - timedelta(days=now.weekday())
            start = datetime(start.year, start.month, start.day, tzinfo=TZ)
            reset_point = start + timedelta(days=7)

        elif period_value == "month":
            if now.month == 12:
                reset_point = datetime(now.year + 1, 1, 1, tzinfo=TZ)
            else:
                reset_point = datetime(now.year, now.month + 1, 1, tzinfo=TZ)

        remaining = max(0, int((reset_point - now).total_seconds()))

        if remaining < 3600:
            # under 1 hour → minutes only
            minutes = -(-remaining // 60)
            time_left = f"{minutes}m"

        elif remaining < 86400:
            # under 24h → hours only
            hours = remaining // 3600
            time_left = f"{hours}h"

        else:
            # 1+ days → days only
            days = remaining // 86400
            time_left = f"{days}d"

        reset_text = f"Next reset in {time_left} • Europe/Stockholm (CET/CEST)"

    embed.set_footer(text=reset_text)
    await interaction.response.send_message(
        embed=embed,
        file=file
    )

@bot.tree.command(
    name="setchannel",
    description="Set the channel for daily automatic rolls"
)
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

# ---------------- ADMIN COMMANDS ----------------

if ADMIN_MODE:

    @bot.tree.command(
        name="export",
        description="Owner-only export",
        guild=discord.Object(id=ADMIN_GUILD_ID)
    )
    async def export_admin(interaction: discord.Interaction):

        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("No.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # ========================
        # GUILD DATA
        # ========================
        guild_buffer = io.StringIO()
        guild_writer = csv.writer(guild_buffer)

        guild_writer.writerow(["guild_id", "guild_name", "member_count"])

        for g in bot.guilds:
            guild_writer.writerow([g.id, g.name, g.member_count])

        guild_file = discord.File(
            io.BytesIO(guild_buffer.getvalue().encode()),
            filename="guilds.csv"
        )

        # ========================
        # GLOBAL BOT STATS
        # ========================
        with db() as con:
            total_users, total_rolls = con.execute("""
                SELECT COUNT(DISTINCT user_id), COUNT(*)
                FROM rolls
                WHERE actor_type = 'user'
            """).fetchone()

            total_bot_rolls = con.execute("""
                SELECT COUNT(*)
                FROM rolls
                WHERE actor_type = 'bot'
            """).fetchone()[0]

        stats_buffer = io.StringIO()
        stats_writer = csv.writer(stats_buffer)

        stats_writer.writerow(["metric", "value"])
        stats_writer.writerow(["guilds", len(bot.guilds)])
        stats_writer.writerow(["users", total_users or 0])
        stats_writer.writerow(["user_rolls", total_rolls or 0])
        stats_writer.writerow(["bot_rolls", total_bot_rolls or 0])

        stats_file = discord.File(
            io.BytesIO(stats_buffer.getvalue().encode()),
            filename="bot_stats.csv"
        )

        await interaction.followup.send(
            content="Admin export:",
            files=[guild_file, stats_file],
            ephemeral=True
        )
    
    @bot.tree.command(
        name="user",
        description="Admin view of a user's roll data",
        guild=discord.Object(id=ADMIN_GUILD_ID)
    )
    async def admin_user(
        interaction: discord.Interaction,
        user: discord.User
    ):

        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("No.", ephemeral=True)
            return

        uid = user.id

        with db() as con:

            rolls = con.execute("""
                SELECT value, rolled_at
                FROM rolls
                WHERE user_id = ?
                  AND actor_type = 'user'
                ORDER BY rolled_at
            """, (uid,)).fetchall()

        if not rolls:
            await interaction.response.send_message(
                "User has no rolls.",
                ephemeral=True
            )
            return

        values = [r[0] for r in rolls]

        total_rolls = len(values)
        best_roll = max(values)
        avg_roll = round(sum(values) / total_rolls, 2)

        current, best = calculate_streaks(uid)

        first_roll = datetime.fromtimestamp(rolls[0][1], TZ).strftime("%Y-%m-%d")
        last_roll = datetime.fromtimestamp(rolls[-1][1], TZ).strftime("%Y-%m-%d")

        await interaction.response.send_message(
            f"User: {user.name}\n"
            f"Rolls: {total_rolls}\n"
            f"Best roll: {best_roll}\n"
            f"Average: {avg_roll}\n"
            f"Current streak: {current}\n"
            f"Best streak: {best}\n"
            f"First roll: {first_roll}\n"
            f"Last roll: {last_roll}",
            ephemeral=True
        )

# ---------------- RUN ----------------
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing")

bot.run(TOKEN)