import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite
import discord
import httpx
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "900"))
DB_PATH = "flight_tracker.db"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("flight_tracker_bot")
logging.getLogger("httpx").setLevel(logging.WARNING)


@dataclass
class FlightOption:
    track_key: str
    title: str
    price: Optional[int]
    currency: str
    details: str
    raw: Dict[str, Any]


class SerpApiClient:
    BASE_URL = "https://serpapi.com/search.json"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.http = httpx.AsyncClient(timeout=25)

    async def close(self) -> None:
        await self.http.aclose()

    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: Optional[str] = None,
        adults: int = 1,
        travel_class: str = "economy",
        max_price: Optional[int] = None,
    ) -> Dict[str, Any]:
        params = {
            "engine": "google_flights",
            "api_key": self.api_key,
            "departure_id": origin.upper(),
            "arrival_id": destination.upper(),
            "departure_date": departure_date,
            "adults": adults,
            # SerpApi Google Flights: type=1 round trip, type=2 one way
            "type": 1 if return_date else 2,
            "travel_class": travel_class,
            "currency": "USD",
            "hl": "en",
            "gl": "us",
        }
        if return_date:
            params["return_date"] = return_date
        if max_price:
            params["max_price"] = max_price

        response = await self.http.get(self.BASE_URL, params=params)
        if response.status_code >= 400:
            error = self._extract_error_message(response)
            raise ValueError(error)
        return response.json()

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:
            return f"SerpApi request failed with status {response.status_code}."
        return (
            payload.get("error")
            or payload.get("message")
            or payload.get("search_metadata", {}).get("status")
            or f"SerpApi request failed with status {response.status_code}."
        )


class FlightRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS tracked_flights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    track_key TEXT NOT NULL,
                    label TEXT NOT NULL,
                    last_price INTEGER,
                    currency TEXT,
                    search_context TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(guild_id, user_id, track_key)
                )
                """
            )
            await db.commit()

    async def add_tracking(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        track_key: str,
        label: str,
        last_price: Optional[int],
        currency: str,
        search_context: Optional[Dict[str, Any]],
    ) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    """
                    INSERT INTO tracked_flights
                    (guild_id, channel_id, user_id, track_key, label, last_price, currency, search_context, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        channel_id,
                        user_id,
                        track_key,
                        label,
                        last_price,
                        currency,
                        json.dumps(search_context) if search_context else None,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def list_tracking(self, guild_id: int, user_id: int) -> List[Tuple[Any, ...]]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT id, label, track_key, last_price, currency, created_at
                FROM tracked_flights
                WHERE guild_id = ? AND user_id = ?
                ORDER BY id DESC
                """,
                (guild_id, user_id),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            return rows

    async def remove_tracking(self, guild_id: int, user_id: int, tracking_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM tracked_flights WHERE id = ? AND guild_id = ? AND user_id = ?",
                (tracking_id, guild_id, user_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def fetch_all_trackings(self) -> List[Tuple[Any, ...]]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT id, guild_id, channel_id, user_id, track_key, label, last_price, currency, search_context
                FROM tracked_flights
                """
            )
            rows = await cursor.fetchall()
            await cursor.close()
            return rows

    async def update_price(self, tracking_id: int, new_price: Optional[int]) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE tracked_flights SET last_price = ? WHERE id = ?",
                (new_price, tracking_id),
            )
            await db.commit()


class TrackButton(discord.ui.Button):
    def __init__(self, option: FlightOption, context_payload: Dict[str, Any]):
        super().__init__(label="Track Price", style=discord.ButtonStyle.success)
        self.option = option
        self.context_payload = context_payload

    async def callback(self, interaction: discord.Interaction):
        repo: FlightRepository = interaction.client.repo  # type: ignore[attr-defined]
        if not interaction.guild_id or not interaction.channel_id or not interaction.user:
            await interaction.response.send_message("This action is only available in a server channel.", ephemeral=True)
            return

        ok = await repo.add_tracking(
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            user_id=interaction.user.id,
            track_key=self.option.track_key,
            label=self.option.title,
            last_price=self.option.price,
            currency=self.option.currency,
            search_context=self.context_payload,
        )
        if ok:
            await interaction.response.send_message(
                f"Tracking enabled for **{self.option.title}** (current: {self.option.currency} {self.option.price}).",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message("You are already tracking this flight.", ephemeral=True)


class SearchResultsView(discord.ui.View):
    def __init__(self, options: List[FlightOption], context_payload: Dict[str, Any]):
        super().__init__(timeout=300)
        for option in options[:5]:
            self.add_item(TrackButton(option, context_payload))


class FlightTrackerBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.repo = FlightRepository(DB_PATH)
        self.serp = SerpApiClient(SERPAPI_KEY)

    async def setup_hook(self):
        await self.repo.init()
        self.price_polling.start()
        synced = await self.tree.sync()
        logger.info("Synced %d slash commands", len(synced))

    async def close(self):
        self.price_polling.cancel()
        await self.serp.close()
        await super().close()

    def parse_options(self, payload: Dict[str, Any]) -> List[FlightOption]:
        combined = payload.get("best_flights", []) + payload.get("other_flights", [])
        options: List[FlightOption] = []
        for entry in combined:
            flights = entry.get("flights", [])
            if not flights:
                continue
            first = flights[0]
            airline = first.get("airline", "Unknown")
            number = first.get("flight_number", "")
            route = f"{first.get('departure_airport', {}).get('id', '?')}→{first.get('arrival_airport', {}).get('id', '?')}"
            title = f"{airline} {number} {route}".strip()
            date_str = first.get("departure_airport", {}).get("time", "")[:10]
            track_key = f"{airline}|{number}|{route}|{date_str}"
            price = entry.get("price")
            options.append(
                FlightOption(
                    track_key=track_key,
                    title=title,
                    price=price,
                    currency="USD",
                    details=f"Duration: {entry.get('total_duration', '?')} mins | Stops: {len(flights) - 1}",
                    raw=entry,
                )
            )
        return options

    def build_embed(self, options: List[FlightOption], title: str) -> discord.Embed:
        embed = discord.Embed(title=title, color=discord.Color.blurple())
        if not options:
            embed.description = "No flights found for that search."
            return embed

        for idx, opt in enumerate(options[:5], start=1):
            embed.add_field(
                name=f"{idx}. {opt.title}",
                value=f"Price: **{opt.currency} {opt.price}**\n{opt.details}\nTrack key: `{opt.track_key}`",
                inline=False,
            )
        return embed

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def price_polling(self):
        trackings = await self.repo.fetch_all_trackings()
        if not trackings:
            return

        for row in trackings:
            tracking_id, guild_id, channel_id, user_id, track_key, label, last_price, currency, search_context = row
            if not search_context:
                continue

            context = json.loads(search_context)
            try:
                payload = await self.serp.search_flights(**context)
                options = self.parse_options(payload)
                match = next((o for o in options if o.track_key == track_key), None)
                if not match or match.price is None:
                    continue

                if last_price is None:
                    await self.repo.update_price(tracking_id, match.price)
                    continue

                if match.price < last_price:
                    channel = self.get_channel(channel_id)
                    if channel and isinstance(channel, discord.TextChannel):
                        await channel.send(
                            f"📉 <@{user_id}> price drop for **{label}**: {currency} {last_price} → {currency} {match.price}"
                        )
                await self.repo.update_price(tracking_id, match.price)
            except Exception as exc:
                logger.warning("Polling error for tracking_id=%s: %s", tracking_id, exc)

    @price_polling.before_loop
    async def before_price_polling(self):
        await self.wait_until_ready()


bot = FlightTrackerBot()


def _validate_iata(code: str) -> bool:
    return len(code) == 3 and code.isalpha()


def _parse_date(raw: str) -> Optional[date]:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


@bot.tree.command(name="search_flights", description="Search flights and add tracking with buttons")
@app_commands.describe(
    origin="Origin airport code (e.g., JFK)",
    destination="Destination airport code (e.g., LAX)",
    departure_date="YYYY-MM-DD",
    return_date="YYYY-MM-DD (optional)",
    adults="Number of adults",
    travel_class="economy, premium_economy, business, first",
    max_price="Max price in USD",
)
async def search_flights(
    interaction: discord.Interaction,
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
    adults: app_commands.Range[int, 1, 9] = 1,
    travel_class: str = "economy",
    max_price: Optional[int] = None,
):
    if not SERPAPI_KEY:
        await interaction.response.send_message("Missing SERPAPI_KEY in environment.", ephemeral=True)
        return
    if not _validate_iata(origin) or not _validate_iata(destination):
        await interaction.response.send_message(
            "Origin and destination must be 3-letter IATA airport codes (e.g., JFK, EWR).",
            ephemeral=True,
        )
        return
    dep = _parse_date(departure_date)
    if dep is None:
        await interaction.response.send_message("`departure_date` must use YYYY-MM-DD.", ephemeral=True)
        return
    if return_date:
        ret = _parse_date(return_date)
        if ret is None:
            await interaction.response.send_message("`return_date` must use YYYY-MM-DD.", ephemeral=True)
            return
        if ret < dep:
            await interaction.response.send_message("`return_date` must be the same day or later than `departure_date`.", ephemeral=True)
            return

    await interaction.response.defer(thinking=True)
    context_payload = {
        "origin": origin,
        "destination": destination,
        "departure_date": departure_date,
        "return_date": return_date,
        "adults": adults,
        "travel_class": travel_class,
        "max_price": max_price,
    }

    try:
        payload = await bot.serp.search_flights(**context_payload)
        options = bot.parse_options(payload)
        embed = bot.build_embed(options, f"Flights {origin.upper()} → {destination.upper()} ({departure_date})")
        view = SearchResultsView(options, context_payload)
        await interaction.followup.send(embed=embed, view=view)
    except ValueError as exc:
        await interaction.followup.send(
            f"Search failed: {exc}\nTip: try major airport codes (e.g., STI → JFK) and valid dates.",
            ephemeral=True,
        )
    except Exception:
        logger.exception("Unexpected error in /search_flights")
        await interaction.followup.send("Search failed due to an unexpected error. Please try again.", ephemeral=True)


@bot.tree.command(name="track", description="Track a flight manually by flight code")
@app_commands.describe(
    flight_code="Flight code or custom tracking key (e.g., UA123)",
    label="Optional display label",
)
async def track(
    interaction: discord.Interaction,
    flight_code: str,
    label: Optional[str] = None,
):
    if not interaction.guild_id or not interaction.channel_id or not interaction.user:
        await interaction.response.send_message("Use this command in a server channel.", ephemeral=True)
        return

    ok = await bot.repo.add_tracking(
        guild_id=interaction.guild_id,
        channel_id=interaction.channel_id,
        user_id=interaction.user.id,
        track_key=flight_code.upper(),
        label=label or f"Manual: {flight_code.upper()}",
        last_price=None,
        currency="USD",
        search_context=None,
    )
    if ok:
        await interaction.response.send_message(f"Tracking started for `{flight_code.upper()}`.")
    else:
        await interaction.response.send_message("You are already tracking that code.", ephemeral=True)


@bot.tree.command(name="list_tracks", description="List your tracked flights")
async def list_tracks(interaction: discord.Interaction):
    if not interaction.guild_id or not interaction.user:
        await interaction.response.send_message("Use this command in a server.", ephemeral=True)
        return

    rows = await bot.repo.list_tracking(interaction.guild_id, interaction.user.id)
    if not rows:
        await interaction.response.send_message("You are not tracking anything yet.", ephemeral=True)
        return

    lines = [
        f"**#{row[0]}** — {row[1]} | key: `{row[2]}` | last: {row[4]} {row[3]}"
        for row in rows
    ]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="untrack", description="Stop tracking a flight by track ID")
@app_commands.describe(track_id="ID from /list_tracks")
async def untrack(interaction: discord.Interaction, track_id: int):
    if not interaction.guild_id or not interaction.user:
        await interaction.response.send_message("Use this command in a server.", ephemeral=True)
        return

    removed = await bot.repo.remove_tracking(interaction.guild_id, interaction.user.id, track_id)
    if removed:
        await interaction.response.send_message(f"Removed tracking #{track_id}.", ephemeral=True)
    else:
        await interaction.response.send_message("Tracking ID not found.", ephemeral=True)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.exception("Unhandled app command error: %s", error)
    if interaction.response.is_done():
        await interaction.followup.send(
            "Something went wrong while running that command. Please try again.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            "Something went wrong while running that command. Please try again.",
            ephemeral=True,
        )


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is required")
    bot.run(DISCORD_TOKEN)
