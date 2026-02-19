# RollF 🎲

RollF is a Discord bot that posts one daily roll and tracks leaderboards.

## Features
- One roll per user per day
- Automatic daily bot roll
- Period-based leaderboards (Today, Week, Month, Year, All Time)
- Persistent SQLite storage

## Try RollF

You can invite the live instance of RollF to your server:

➜ https://discord.com/oauth2/authorize?client_id=1409207722783543347&permissions=2147568640&integration_type=0&scope=bot+applications.commands

Note: this is my personal AND official instance that's also available on top.gg

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

