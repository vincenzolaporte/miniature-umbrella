# Flight Price Tracker Discord Bot

A Discord bot that searches Google Flights via SerpApi and lets users track price changes.

## 1) Create the Discord application + bot (Developer Portal)

Go to: https://discord.com/developers/applications

1. Click **New Application** and give it a name (for example: `Flight Price Tracker`).
2. Open your app, then go to **Bot** in the left sidebar.
3. Click **Add Bot**.
4. Under **Privileged Gateway Intents**, you can leave all toggles OFF for this project (the bot uses slash commands and standard channel messaging).
5. In **Token**, click **Reset Token** (or **Copy**) and save this value as `DISCORD_TOKEN` in your `.env`.

## 2) Configure install settings (slash commands + permissions)

Inside the same app:

1. Go to **Installation**.
2. Under **Install Link**, choose **Discord Provided Link**.
3. Under **Default Install Settings**:
   - **Scopes**: enable `bot` and `applications.commands`
   - **Bot Permissions**: at minimum enable:
     - `View Channels`
     - `Send Messages`
     - `Embed Links`
     - `Read Message History`
4. Copy the generated install URL and open it in a browser.
5. Select your server and authorize the bot.

## 3) Create and configure SerpApi key

1. Create/login to your SerpApi account.
2. Copy your API key.
3. Put it in `.env` as `SERPAPI_KEY`.

## 4) Local project setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Now edit `.env`:

```env
DISCORD_TOKEN=your_discord_bot_token
SERPAPI_KEY=your_serpapi_key
POLL_INTERVAL_SECONDS=900
```

## 5) Start the bot

```bash
python bot.py
```

If you're on Windows and `python` is not recognized, use:

```powershell
py bot.py
```

On first run, the bot syncs slash commands. In Discord, type `/` and you should see:

- `/search_flights`
- `/track`
- `/list_tracks`
- `/untrack`

## 6) How to use it

### Search + one-click track

Use:

`/search_flights origin:JFK destination:LAX departure_date:2026-04-20`

The bot will return results with **Track Price** buttons. Click one to start tracking.

### Manual track by code

Use:

`/track flight_code:UA123`

### List / remove tracked items

- `/list_tracks`
- `/untrack track_id:<id from list>`

## Troubleshooting

- **Commands do not appear**: remove/re-invite the bot with `applications.commands` scope enabled.
- **Bot is offline**: re-check `DISCORD_TOKEN` and that `python bot.py` is running.
- **Windows says `python` not found**: use `py bot.py` instead.
- **SerpApi errors**: verify `SERPAPI_KEY`, account quota, and API access.
- **400 Bad Request from SerpApi**: confirm airport codes are valid 3-letter IATA values and date format is `YYYY-MM-DD`.
- **No alerts yet**: alerts are sent when a tracked item is found again with a lower price than previously stored.
## Features

- `/search_flights` slash command to search flights with filters.
- Buttons on search results to quickly **Track Price** for a flight.
- `/track` command to track a flight by code manually.
- `/list_tracks` and `/untrack` to manage tracked flights.
- Background polling that sends alerts when a tracked flight drops in price.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy env file:
   ```bash
   cp .env.example .env
   ```
4. Fill in `DISCORD_TOKEN` and `SERPAPI_KEY` in `.env`.
5. Start bot:
   ```bash
   python bot.py
   ```

## Commands

- `/search_flights origin destination departure_date [return_date] [adults] [travel_class] [max_price]`
- `/track flight_code [label]`
- `/list_tracks`
- `/untrack track_id`

### Date format

Use `YYYY-MM-DD` (example: `2026-04-20`).

## Notes

- Search uses SerpApi `engine=google_flights`.
- Best tracking quality comes from button-based tracking because full search context is saved.
- Price tracking works best for search-driven tracking (buttons) because the bot keeps full search context.
