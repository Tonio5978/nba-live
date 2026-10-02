import asyncio
import aiohttp
from datetime import datetime, timedelta
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import (
    _LOGGER,
    CONF_ENTRY_TYPE,
    CONF_TEAM_ID,
    CONF_TEAM_NAME,
    DOMAIN,
    ENTRY_TYPE_TEAM,
    NBA_API_URL,
)

# Intervalles de mise à jour
SCAN_INTERVAL_LIVE = timedelta(seconds=10)     # Match en cours
SCAN_INTERVAL_IDLE = timedelta(minutes=10)     # Pas de match en cours
# HA appelle async_update à ce rythme ; async_update saute ensuite l'appel
# tant que l'intervalle effectif (live ou idle) n'est pas écoulé.
SCAN_INTERVAL = SCAN_INTERVAL_LIVE
# Tolérance pour ne pas sauter un cycle à quelques millisecondes près
UPDATE_TOLERANCE = timedelta(seconds=1)

# Durée de vie du cache par URL : courte si la réponse contient un match en
# cours, sinon plus longue (journée passée, matchs à venir...). Toujours
# inférieure à l'intervalle correspondant pour ne pas servir une donnée périmée.
CACHE_TTL_LIVE = timedelta(seconds=5)
CACHE_TTL_IDLE = timedelta(minutes=5)

STANDINGS_URL = "https://site.web.api.espn.com/apis/v2/sports/basketball/nba/standings"
# Fenêtre du scoreboard, en jours relatifs : J-1 à J+4
SCOREBOARD_DAYS = range(-1, 5)
# Types de saison ESPN, dans l'ordre chronologique :
# présaison, saison régulière, play-in, playoffs
NBA_SEASON_TYPES = (1, 2, 5, 3)

# Attributs volumineux exclus de la base du recorder (limite HA : 16 Ko)
UNRECORDED_ATTRIBUTES = frozenset({
    "matches",
    "standings",
    "standings_groups",
    "league_info",
})


def _current_nba_season(now=None):
    """Retourne (season_year, début, fin) de la saison NBA courante.

    ESPN identifie une saison par l'année de sa fin (2026-27 -> 2027).
    La bascule se fait au 1er juillet, après les Finales, pour afficher
    le calendrier de la saison suivante pendant l'intersaison.
    """
    now = now or datetime.now()
    season_year = now.year + 1 if now.month >= 7 else now.year
    return season_year, datetime(season_year - 1, 7, 1), datetime(season_year, 6, 30)


def _payload_has_live(data):
    """True si une réponse ESPN (scoreboard ou calendrier) contient un match en cours."""
    for event in data.get("events", []):
        # scoreboard : status au niveau de l'event ; calendrier : au niveau de la compétition
        status = event.get("status") or (event.get("competitions") or [{}])[0].get("status", {})
        if status.get("type", {}).get("state") == "in":
            return True
    return False


def _next_calendar_day(data, from_day):
    """Premier jour de match du calendrier ESPN à partir de from_day, ou None."""
    leagues = data.get("leagues") or [{}]
    for entry in leagues[0].get("calendar", []):
        # Liste de dates pour la NBA ; des objets {startDate: ...} pour d'autres ligues
        value = entry.get("startDate", "") if isinstance(entry, dict) else entry
        try:
            day = datetime.strptime(value[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        if day >= from_day:
            return day
    return None


def _slug(name):
    return name.replace(" ", "_").replace(".", "_").lower()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    if entry.data[CONF_ENTRY_TYPE] == ENTRY_TYPE_TEAM:
        team_id = entry.data[CONF_TEAM_ID]
        team_name = entry.data[CONF_TEAM_NAME]
        slug = _slug(team_name)
        sensors = [
            NbaLiveSensor(entry, "next_match", "nba_team_next_match", f"nbalive_next_{slug}",
                          device_name=team_name, team_id=team_id),
            NbaLiveSensor(entry, "schedule", "nba_team_schedule", f"nbalive_nba_team_{slug}",
                          device_name=team_name, team_id=team_id),
        ]
    else:
        sensors = [
            NbaLiveSensor(entry, "standings_east", "standings", "nbalive_classifica_nba_east",
                          device_name="NBA", conference="East"),
            NbaLiveSensor(entry, "standings_west", "standings", "nbalive_classifica_nba_west",
                          device_name="NBA", conference="West"),
            NbaLiveSensor(entry, "matches", "match_day", "nbalive_all_nba", device_name="NBA"),
        ]

    async_add_entities(sensors, True)


class NbaLiveSensor(SensorEntity):
    _cache = {}
    _unrecorded_attributes = UNRECORDED_ATTRIBUTES
    _attr_has_entity_name = True
    _attr_icon = "mdi:basketball"

    def __init__(self, entry, key, sensor_type, object_id, device_name, team_id=None, conference=None):
        """
        Args:
            key: clé du capteur (unique_id et nom traduit)
            sensor_type: type de données traité (standings, match_day, nba_team_*)
            object_id: entity_id proposé à la création (préfixe nbalive_ historique)
        """
        self._sensor_type = sensor_type
        self._team_id = team_id
        self._conference = conference
        self._state = None
        self._attributes = {}
        # Période couverte, affichée en attributs (fenêtre du scoreboard, saison...)
        self._start_date = None
        self._end_date = None

        # Tracking for live matches
        self._has_live_match = False
        self._last_update_time = None

        self.entity_id = f"sensor.{object_id}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=device_name,
            manufacturer="ESPN",
            model="NBA",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.espn.com/nba/",
        )

    @property
    def native_value(self):
        return self._state

    @property
    def extra_state_attributes(self):
        attributes = {
            **self._attributes,
            "has_live_match": self._has_live_match,
            "update_interval": self._get_update_interval_seconds(),
        }
        if self._start_date and self._end_date:
            attributes["start_date"] = self._start_date.strftime("%Y-%m-%d")
            attributes["end_date"] = self._end_date.strftime("%Y-%m-%d")
        return attributes

    def _get_update_interval_seconds(self):
        """Retourne l'intervalle de mise à jour en secondes"""
        interval = SCAN_INTERVAL_LIVE if self._has_live_match else SCAN_INTERVAL_IDLE
        return int(interval.total_seconds())

    def _check_for_live_matches(self, matches_data):
        """True si au moins un match est en cours.

        state vaut "pre", "in" ou "post" ; "in" couvre aussi la mi-temps
        et les fins de quart-temps (status "Halftime", "End of Period").
        """
        return any(match.get("state") == "in" for match in matches_data or [])

    async def async_update(self):
        """Mise à jour avec intervalle dynamique"""
        now = datetime.now()

        # Calculer l'intervalle basé sur l'état actuel
        update_interval = SCAN_INTERVAL_LIVE if self._has_live_match else SCAN_INTERVAL_IDLE

        # Vérifier si on doit faire une mise à jour
        if self._last_update_time is not None:
            time_since_update = now - self._last_update_time
            if time_since_update < update_interval - UPDATE_TOLERANCE:
                _LOGGER.debug(
                    f"Skipping update for {self.entity_id} - "
                    f"Last update: {time_since_update.total_seconds():.0f}s ago, "
                    f"Interval: {update_interval.total_seconds():.0f}s, "
                    f"Live match: {self._has_live_match}"
                )
                return

        _LOGGER.debug(
            f"Starting update for {self.entity_id} - "
            f"Interval: {update_interval.total_seconds():.0f}s, "
            f"Live match: {self._has_live_match}"
        )

        data = await self._fetch_data()
        if data is not None:
            await self._process_data(data)
            _LOGGER.debug(f"Finished update for {self.entity_id}")

        # Même en cas d'erreur : on réessaiera au prochain intervalle
        self._last_update_time = now

    async def _fetch_data(self):
        """Récupère les données brutes ESPN du capteur, ou None en cas d'erreur."""
        if self._sensor_type == "match_day":
            return await self._fetch_scoreboard()
        if self._sensor_type in ("nba_team_schedule", "nba_team_next_match"):
            return await self._fetch_team_schedule()
        return await self._fetch_json(STANDINGS_URL)

    async def _fetch_json(self, url):
        """GET JSON avec cache partagé par URL entre tous les capteurs."""
        now = datetime.now()
        cached = NbaLiveSensor._cache.get(url)
        if cached and now < cached["expires"]:
            _LOGGER.debug(f"Using cached data for {url}")
            return cached["data"]

        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                data = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.warning(f"Erreur lors de la requête {url} : {err}")
            return None

        # Purge des entrées expirées (les URLs datées changent chaque jour)
        for key in [k for k, v in NbaLiveSensor._cache.items() if v["expires"] <= now]:
            del NbaLiveSensor._cache[key]

        ttl = CACHE_TTL_LIVE if _payload_has_live(data) else CACHE_TTL_IDLE
        NbaLiveSensor._cache[url] = {"data": data, "expires": now + ttl}
        return data

    async def _fetch_scoreboard_days(self, days):
        """Un appel par jour : ESPN refuse les plages dates=AAAAMMJJ-AAAAMMJJ (HTTP 400)."""
        payloads = await asyncio.gather(*(
            self._fetch_json(f"{NBA_API_URL}/scoreboard?dates={day:%Y%m%d}")
            for day in days
        ))
        if any(payload is None for payload in payloads):
            return None
        return payloads

    async def _fetch_scoreboard(self):
        """Matchs de J-1 à J+4.

        Si la fenêtre est vide (intersaison, trêve), on affiche à la place les
        5 jours à partir du prochain jour de match du calendrier ESPN.
        """
        today = datetime.now().date()
        days = [today + timedelta(days=offset) for offset in SCOREBOARD_DAYS]
        payloads = await self._fetch_scoreboard_days(days)
        if payloads is None:
            return None

        events = [event for payload in payloads for event in payload.get("events", [])]
        if not events:
            next_day = _next_calendar_day(payloads[0], today)
            if next_day is None:
                # En juillet-août, le calendrier d'une date est celui de la saison
                # terminée ; le scoreboard par défaut pointe sur la saison à venir.
                default = await self._fetch_json(f"{NBA_API_URL}/scoreboard")
                next_day = _next_calendar_day(default, today) if default else None
            if next_day is not None:
                days = [next_day + timedelta(days=offset) for offset in range(len(SCOREBOARD_DAYS))]
                payloads = await self._fetch_scoreboard_days(days)
                if payloads is None:
                    return None
                events = [event for payload in payloads for event in payload.get("events", [])]

        self._start_date = datetime.combine(days[0], datetime.min.time())
        self._end_date = datetime.combine(days[-1], datetime.min.time())
        return {"leagues": payloads[0].get("leagues", []), "events": events}

    async def _fetch_team_schedule(self):
        """Calendrier complet de la saison (tous types de saison confondus).

        Sans seasontype, ESPN ne renvoie que le type en cours (ex. la seule
        présaison en octobre), d'où un appel par type.
        """
        season_year, _, _ = _current_nba_season()
        payloads = await asyncio.gather(*(
            self._fetch_json(
                f"{NBA_API_URL}/teams/{self._team_id}/schedule?season={season_year}&seasontype={season_type}"
            )
            for season_type in NBA_SEASON_TYPES
        ))
        if any(payload is None for payload in payloads):
            return None

        events = {}
        for payload in payloads:
            for event in payload.get("events", []):
                events[event.get("id")] = event
        team = next((p["team"] for p in payloads if p.get("team")), {})
        return {
            "team": team,
            "events": sorted(events.values(), key=lambda event: event.get("date", "")),
        }

    async def _process_data(self, data):
        if self._sensor_type == "standings":
            from .sensori.classifica import classifica_data
            processed_data = classifica_data(data, self._conference)
            conf_label = self._conference if self._conference else "NBA"
            self._state = f"NBA Standings {conf_label}"
            self._attributes = processed_data
            self._has_live_match = False

        elif self._sensor_type in ("nba_team_schedule", "nba_team_next_match"):
            from .sensori.schedule import process_nba_team_schedule
            from .sensori.scoreboard import is_within_last_48_hours
            # L'URL étant déjà limitée à la saison, aucun filtre de date n'est appliqué
            _, self._start_date, self._end_date = _current_nba_season()
            schedule_data = await process_nba_team_schedule(data, self.hass)
            matches = schedule_data.get("matches", [])
            self._has_live_match = self._check_for_live_matches(matches)

            if self._sensor_type == "nba_team_next_match":
                live = [m for m in matches if m.get("state") == "in"]
                recent = [m for m in matches if m.get("state") == "post" and is_within_last_48_hours(m.get("date", ""))]
                upcoming = [m for m in matches if m.get("state") == "pre"]
                # À défaut, le dernier match joué de la saison
                next_match = (live or recent or upcoming)[:1] or matches[-1:]

                if next_match:
                    m = next_match[0]
                    if m.get("state") == "in":
                        self._state = f"{m['home_score']} - {m['away_score']} ({m['clock']})"
                    else:
                        self._state = f"{m.get('home_team', 'N/A')} vs {m.get('away_team', 'N/A')}"
                else:
                    self._state = "Aucun match disponible"

                self._attributes = {
                    "team_name": schedule_data.get("team_name", "N/A"),
                    "team_logo": schedule_data.get("team_logo", "N/A"),
                    "matches": next_match,
                }

            else:
                live_matches = [m for m in matches if m.get("state") == "in"]
                if live_matches:
                    m = live_matches[0]
                    self._state = f"{m['home_score']} - {m['away_score']} ({m['clock']})"
                elif matches:
                    self._state = f"{len(matches)} matchs - {schedule_data.get('team_name', 'N/A')}"
                else:
                    self._state = "Aucun match disponible"

                self._attributes = {
                    "team_name": schedule_data.get("team_name", "N/A"),
                    "team_logo": schedule_data.get("team_logo", "N/A"),
                    "matches": matches,
                }

        elif self._sensor_type == "match_day":
            from .sensori.scoreboard import process_match_data
            # La fenêtre J-1 à J+4 est déjà appliquée par _fetch_scoreboard
            match_data = await process_match_data(data, self.hass)
            matches = match_data.get("matches", [])
            self._has_live_match = self._check_for_live_matches(matches)

            self._state = "Matches of the Week"
            self._attributes = {
                "league_info": match_data.get("league_info", "N/A"),
                "matches": matches
            }

            _LOGGER.debug(f"{self.entity_id}: Found {len(matches)} matches, {sum(1 for m in matches if m.get('state') == 'in')} live")
