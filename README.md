# Flight Price Tracker Discord Bot

A Discord bot that searches Google Flights via SerpApi and lets users track price changes.

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
- Price tracking works best for search-driven tracking (buttons) because the bot keeps full search context.
