# RollF 🎲

RollF is a minimal daily roll Discord bot built around one simple idea:

Everyone gets exactly one roll per day (1–100).

No rerolls. No economy. No gambling mechanics.
Just a daily number and some competition.

---

## Features

- One roll per user per calendar day (Europe/Stockholm)
- Roll range: 1–100
- Automatic daily bot roll
- Period-based leaderboards:
  - Today
  - Week
  - Month
  - Year
  - All Time
  - Longest Streaks
- Streak tracking (current and best)
- Streak milestone notifications (10 / 100 / 500 / 1000 days)
- Detailed user statistics:
  - Rank
  - Best roll
  - Averages
  - Period breakdown (week & month)
- Reset timers for active periods
- Persistent SQLite storage
- Automated compressed weekly database backups (180-day retention)

---


## Commands

- `/roll` – Roll your daily number
- `/leaderboards` – View period-based rankings
- `/stats` – View detailed statistics
- `/setchannel` – Configure daily bot roll channel (admin)
- `/help` – Show setup information (admin)

---

### Example Roll

![Roll Demo](https://raw.githubusercontent.com/hegernat/rollf-bot/main/assets/roll-example.gif)

---

## Try RollF

You can invite the live instance of RollF to your server:

➜ https://discord.com/oauth2/authorize?client_id=1409207722783543347&permissions=2147568640&integration_type=0&scope=bot+applications.commands

Note: this is my personal & official instance that's also available through top.gg

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
```

Run the bot:
```
python rollf.py
```
