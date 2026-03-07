# RollF 🎲

![License](https://img.shields.io/badge/license-MIT-green)
![Version](https://img.shields.io/github/v/release/hegernat/rollf-bot)
![Discord Bot](https://img.shields.io/badge/bot-live-blue)

[![Invite RollF](https://img.shields.io/badge/Invite-RollF-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.com/oauth2/authorize?client_id=1409207722783543347&permissions=2147568640&integration_type=0&scope=bot+applications.commands)

RollF is a minimal daily roll Discord bot built around one simple idea:

Everyone gets exactly **one roll per day** (1–100).

No rerolls.  
No economy.  
No gambling mechanics.

Just a daily number and some competition.

RollF is the official public instance operated by the original author.
The source code for the bot is available here on GitHub.

---

## Features

- One roll per user per calendar day (Europe/Stockholm)
- Roll range: 1–100
- Automatic daily bot roll
- Global cross-server leaderboards
- Period-based leaderboards:
  - Today
  - Week
  - Month
  - Year
  - All Time
  - Longest Streaks
- Leaderboard position delta (distance to next rank)
- Streak tracking (current and best)
- Streak milestone notifications (10 / 100 / 500 / 1000 days)
- Detailed user statistics:
  - Rank
  - Best roll
  - Averages
  - Period breakdown (week & month)
- Special display for perfect roll (💯)
- Reset timers for active periods
- Persistent SQLite storage
- Automated compressed weekly database backups (180-day retention)
- Owner admin tools for maintenance

---

## Commands

Public:

- `/roll` – Roll your daily number
- `/leaderboards` – View period-based rankings
- `/stats` – View detailed statistics
- `/setchannel` – Configure daily bot roll channel (admin)
- `/help` – Show setup information (admin)

Owner-only (optional, requires ADMIN_MODE=true):

- `/undo` – Delete latest roll for a user
- `/export` – Export guild & global bot statistics
- `/user` – View full roll history summary for a user
- `/forceroll` – Insert a manual roll
- `/purgeuser` – Delete all rolls for a user

---

### Example Roll

![Roll Demo](https://raw.githubusercontent.com/hegernat/rollf-bot/main/assets/roll-example.gif)

---

## Try RollF

Use the invite button at the top of this page to add RollF to your server.

RollF is also available on top.gg:
https://top.gg/bot/1409207722783543347

---

## Requirements

For RollF to function correctly, the bot needs permission to:

- Send messages
- Embed links
- Read message history
- Use slash commands

Daily bot rolls are posted in the configured channel using `/setchannel`.

---

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
Create a .env file in the project root:
```
DISCORD_TOKEN=your_token_here
ADMIN_MODE=true
OWNER_ID=your_user_id_here
ADMIN_GUILD_ID=your_server_id_here
```

Run the bot:
```
python rollf.py
```
---

## Admin Mode (Optional)

RollF supports an optional admin mode for maintenance tasks.

Admin commands are:

- Only registered if `ADMIN_MODE=true`
- Restricted to `ADMIN_GUILD_ID`
- Usable only by `OWNER_ID`

If `ADMIN_MODE=false`, admin commands are not registered at all.

Example `.env`:
```env
DISCORD_TOKEN=your_token_here
ADMIN_MODE=true
OWNER_ID=your_user_id_here
ADMIN_GUILD_ID=your_server_id_here
```

---

## Production Notes

- Designed for long-term unattended operation
- Uses SQLite (WAL mode recommended)
- Compatible with systemd service deployment
- Supports automated compressed database backups

RollF performs automatic schema migrations on startup,
including backfilling roll_date for historical roll records.

The bot is intentionally minimal and avoids complex state mutations.
All statistics are derived directly from stored roll history.

---

## Name & Official Instance

RollF is open source under the MIT license.

However, the name **"RollF"** and the official public bot instance are maintained by the original author. 
Forks and modified versions are welcome, but please do not present them as the official RollF bot.

If you run your own instance, please use a different bot name to avoid confusion with the official deployment.