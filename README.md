# Pokemon Tradeshow Notifier (Singapore)

A Telegram bot that automatically notifies a group about upcoming Pokemon tradeshows in Singapore.

## Features

- Monitors upcoming Pokemon Trading Card Game (TCG) events and tradeshows in Singapore
- Posts automatic notifications to a Telegram group
- Scheduled reminders for upcoming events

## Setup

1. Clone the repo
2. Copy `.env.example` to `.env` and fill in your credentials
3. Install dependencies: `pip install -r requirements.txt`
4. Run the bot: `python bot.py`

## Environment Variables

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | The group chat ID to post notifications to |

## License

MIT
