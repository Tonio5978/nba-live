import asyncio
import aiohttp
from datetime import datetime, timedelta
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import Entity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import random
from .const import DOMAIN, _LOGGER

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

NBA_API_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
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

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    try:
        competition_name = entry.data.get("name")
        competition_code = entry.data.get("competition_code")
        team_name = entry.data.get("team_name")
        selection = entry.data.get("selection")
        team_id = entry.data.get("team_id")
        #{'competition_code': 'uefa.champions', 'end_date': '2025-07-26', 'name': 'Team UEFA Champions League Internazionale', 'selection': 'Team', 'start_date': '2024-11-27', 'team_name': 'Internazionale'}
        
#        _LOGGER.error(f"Entry data completo: {entry.data}")
#        _LOGGER.error(f"Entry options completo: {entry.options}")
                
        start_date_1 = entry.data.get("start_date")
        end_date_1 = entry.data.get("end_date")
        
        start_date = entry.data.get("start_date", datetime.now().strftime("%Y-%m-%d"))
        end_date = entry.data.get("end_date", (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"))
        
        
        base_scan_interval = timedelta(minutes=entry.options.get("scan_interval", 3))
        sensors = []

        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = {}
        
        _LOGGER.debug(f"Calcio Live Config Entry: {entry.data}")  # Log per capire cosa c'è nell'entry
    
        if selection == "Équipe NBA":
            team_name_normalized = team_name.replace(" ", "_").replace(".", "_").lower()
            sensors += [
                CalcioLiveSensor(
                    hass, f"nbalive_next_{team_name_normalized}", "nba", "nba_team_next_match",
                    SCAN_INTERVAL_IDLE, team_name=team_name,
                    config_entry_id=entry.entry_id, start_date=start_date, end_date=end_date, team_id=team_id
                ),
                CalcioLiveSensor(
                    hass, f"nbalive_nba_team_{team_name_normalized}", "nba", "nba_team_schedule",
                    SCAN_INTERVAL_IDLE, team_name=team_name,
                    config_entry_id=entry.entry_id, start_date=start_date, end_date=end_date, team_id=team_id
                ),
            ]

        elif team_name:
            team_name_normalized = team_name.replace(" ", "_").replace(".", "_").lower()
            competition_name = competition_code.replace(" ", "_").replace(".", "_").lower()

            sensors += [
                CalcioLiveSensor(
                    hass, f"nbalive_next_{competition_name}_{team_name_normalized}", competition_code, "team_match",
                    base_scan_interval + timedelta(seconds=random.randint(0, 30)), team_name=team_name,
                    config_entry_id=entry.entry_id, start_date=start_date, end_date=end_date, team_id=team_id
                ),
                CalcioLiveSensor(
                    hass, f"nbalive_all_{competition_name}_{team_name_normalized}", competition_code, "team_matches",
                    base_scan_interval + timedelta(seconds=random.randint(0, 30)), team_name=team_name,
                    config_entry_id=entry.entry_id, start_date=start_date, end_date=end_date, team_id=team_id
                ),
                CalcioLiveSensor(
                    hass, f"nbalive_all_mixed_{team_name_normalized}", competition_code, "team_matches_mixed",
                    base_scan_interval + timedelta(seconds=random.randint(0, 30)), team_name=team_name,
                    config_entry_id=entry.entry_id, start_date=start_date, end_date=end_date, team_id=team_id
                )
            ]
        elif competition_code:
            if competition_code == "99999":  # Se il competition_code è fittizio, crea il sensore per tutte le partite
                sensors += [
                    CalcioLiveSensor(
                        hass, "nbalive_all_today", competition_code, "all_matches_today",
                        base_scan_interval + timedelta(seconds=random.randint(0, 30)), config_entry_id=entry.entry_id,
                        start_date=start_date, end_date=end_date, team_id=team_id
                    )
                ]
            else:
                competition_name = competition_name.replace(" ", "_").replace(".", "_").lower()

                sensors += [
                    CalcioLiveSensor(
                        hass, "nbalive_classifica_nba_east", competition_code, "standings",
                        SCAN_INTERVAL_IDLE, config_entry_id=entry.entry_id,
                        start_date=start_date, end_date=end_date, team_id=team_id, conference="East"
                    ),
                    CalcioLiveSensor(
                        hass, "nbalive_classifica_nba_west", competition_code, "standings",
                        SCAN_INTERVAL_IDLE, config_entry_id=entry.entry_id,
                        start_date=start_date, end_date=end_date, team_id=team_id, conference="West"
                    ),
                    CalcioLiveSensor(
                        hass, f"nbalive_all_nba", competition_code, "match_day",
                        base_scan_interval + timedelta(seconds=random.randint(0, 30)), config_entry_id=entry.entry_id,
                        start_date=start_date, end_date=end_date, team_id=team_id
                    )
                ]

        async_add_entities(sensors, True)

    except Exception as e:
        _LOGGER.error(f"Errore durante la configurazione dei sensori: {e}")


class CalcioLiveSensor(Entity):
    _cache = {}
    _unrecorded_attributes = UNRECORDED_ATTRIBUTES

    def __init__(self, hass, name, code, sensor_type=None, scan_interval=timedelta(seconds=5),
                 team_name=None, config_entry_id=None, start_date=None, end_date=None, team_id=None, conference=None):
        self.hass = hass
        self.interval = timedelta(seconds=10)
        self._name = name
        self._code = code
        self._team_id = team_id
        self._sensor_type = sensor_type
        self._scan_interval = scan_interval
        self._state = None
        self._attributes = {}
        self._config_entry_id = config_entry_id
        self._team_name = team_name
        self._conference = conference
        # Usa le date fornite dal config_entry
        self._start_date = start_date  # (start_date o valore di default)
        self._end_date = end_date      # (end_date o valore di default)
        
        # Conversione delle date in oggetti datetime
        self._start_date = datetime.strptime(self._start_date, "%Y-%m-%d")
        self._end_date = datetime.strptime(self._end_date, "%Y-%m-%d")
        
        self._request_count = 0
        self._last_request_time = datetime.now()
        
        # Tracking for live matches
        self._has_live_match = False
        self._last_update_time = None

        self.base_url = "https://site.web.api.espn.com/apis/v2/sports/soccer"
        self.base_url_2 = "https://site.api.espn.com/apis/site/v2/sports/basketball"
        self.base_url_3 = "https://site.web.api.espn.com/apis/site/v2/sports/soccer"
        
        
    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return {
            **self._attributes,
            "request_count": self._request_count,
            "last_request_time": self._last_request_time,
            "start_date": self._start_date.strftime("%Y-%m-%d"),
            "end_date": self._end_date.strftime("%Y-%m-%d"),
            "has_live_match": self._has_live_match,
            "update_interval": self._get_update_interval_seconds(),
        }

    def _get_update_interval_seconds(self):
        """Retourne l'intervalle de mise à jour en secondes"""
        if self._has_live_match:
            return 10  # 10 secondes si match live
        else:
            return 600  # 10 minutes sinon
    
    def _check_for_live_matches(self, matches_data):
        """
        Vérifie s'il y a des matchs en cours (state = 'in')
        
        Args:
            matches_data: Liste des matchs
            
        Returns:
            bool: True si au moins un match est en cours
        """
        if not matches_data:
            return False
        
        # state vaut "pre", "in" ou "post" ; "in" couvre aussi la mi-temps
        # et les fins de quart-temps (status "Halftime", "End of Period").
        return any(match.get("state") == "in" for match in matches_data)

    @property
    def should_poll(self):
        return True
    
    async def async_added_to_hass(self):
        """Appelé quand l'entité est ajoutée à Home Assistant"""
        await super().async_added_to_hass()
        # Forcer la première mise à jour immédiate
        self._last_update_time = None

    async def async_will_remove_from_hass(self):
        """Appelé avant que l'entité soit retirée"""
        await super().async_will_remove_from_hass()


    @property
    def unique_id(self):
        return f"{self._name}_{self._sensor_type}"

    @property
    def config_entry_id(self):
        return self._config_entry_id

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
                    f"Skipping update for {self._name} - "
                    f"Last update: {time_since_update.total_seconds():.0f}s ago, "
                    f"Interval: {update_interval.total_seconds():.0f}s, "
                    f"Live match: {self._has_live_match}"
                )
                return
        
        _LOGGER.info(
            f"Starting update for {self._name} - "
            f"Interval: {update_interval.total_seconds():.0f}s, "
            f"Live match: {self._has_live_match}"
        )

        data = await self._fetch_data()
        if data is not None:
            await self._process_data(data)
            _LOGGER.info(f"Finished update for {self._name}")

        # Même en cas d'erreur : on réessaiera au prochain intervalle
        self._last_update_time = now

    async def _fetch_data(self):
        """Récupère les données brutes ESPN du capteur, ou None en cas d'erreur."""
        if self._sensor_type in ("match_day", "team_match", "team_matches"):
            return await self._fetch_scoreboard()
        if self._sensor_type in ("nba_team_schedule", "nba_team_next_match"):
            return await self._fetch_team_schedule()

        url = await self._build_url()
        _LOGGER.debug(f"url asked : {url}")
        if url is None:
            return None
        return await self._fetch_json(url)

    async def _fetch_json(self, url):
        """GET JSON avec cache partagé par URL entre tous les capteurs."""
        now = datetime.now()
        cached = CalcioLiveSensor._cache.get(url)
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
        for key in [k for k, v in CalcioLiveSensor._cache.items() if v["expires"] <= now]:
            del CalcioLiveSensor._cache[key]

        ttl = CACHE_TTL_LIVE if _payload_has_live(data) else CACHE_TTL_IDLE
        CalcioLiveSensor._cache[url] = {"data": data, "expires": now + ttl}
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

    async def _build_url(self):
        base_url_2  = "https://site.api.espn.com/apis/site/v2/sports/basketball"
        base_url_3  = "https://site.web.api.espn.com/apis/site/v2/sports/soccer"

        standings_url = "https://site.web.api.espn.com/apis/v2/sports/basketball/nba/standings?"
        all_matches_today_url = f"{base_url_2}/all/scoreboard"
        team_url_schedule_mixed = f"{base_url_3}/all/teams/{self._team_id}/schedule?fixture=true"

        if self._sensor_type == "standings":
            return standings_url
        elif self._sensor_type == "team_matches_mixed" and self._team_name:
            return team_url_schedule_mixed
        elif self._sensor_type == "all_matches_today":
            return all_matches_today_url

        return None
    
    
    async def _get_calendar_data(self):
        """Recupera il calendario delle partite per ottenere le date di inizio e fine"""
    
        if self._code == "99999":
           # _LOGGER.warning("Competition code 99999 escluso dal recupero del calendario.")
            return None, None

        calendar_url = f"{self.base_url_2}/nba/scoreboard"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(calendar_url) as response:
                    response.raise_for_status()
                    data = await response.json()
                    # Estrai le date di inizio e fine dal calendario
                    calendar_start_date = data.get("calendarStartDate", "2024-07-01T04:00Z")
                    calendar_end_date = data.get("calendarEndDate", "2025-07-01T03:59Z")
                    return calendar_start_date, calendar_end_date
        except Exception as e:
            _LOGGER.error(f"Erreur lors de la récupération du calendrier: {e}")
            return None, None


    async def _process_data(self, data):
        from .sensori.scoreboard import process_match_data

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
            # Dates de saison recalculées à chaque mise à jour (celles stockées
            # dans l'entrée datent de la configuration et deviennent obsolètes).
            # L'URL étant déjà limitée à la saison, aucun filtre de date n'est appliqué.
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

                self._has_live_match = bool(live)
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
            # La fenêtre J-1 à J+4 est déjà appliquée par _fetch_scoreboard
            match_data = await process_match_data(data, self.hass)
            matches = match_data.get("matches", [])
            
            # Détecter si un match est live
            self._has_live_match = self._check_for_live_matches(matches)
            
            self._state = "Matches of the Week"
            self._attributes = {
                "league_info": match_data.get("league_info", "N/A"),
                "matches": matches
            }
            
            _LOGGER.debug(f"{self._name}: Found {len(matches)} matches, {sum(1 for m in matches if m.get('state') == 'in')} live")
        
        elif self._sensor_type in ["team_matches", "team_match", "team_matches_mixed", "all_matches_today"]:
            # Capteurs scoreboard : fenêtre déjà appliquée par _fetch_scoreboard
            filter_dates = self._sensor_type not in ("team_match", "team_matches")

            async def get_team_match_data(next_match_only=False):
                return await process_match_data(
                    data, self.hass, team_name=self._team_name, next_match_only=next_match_only,
                    start_date=self._start_date.strftime("%Y-%m-%d") if filter_dates else None,
                    end_date=self._end_date.strftime("%Y-%m-%d") if filter_dates else None,
                )

            if self._sensor_type in ["team_matches", "team_matches_mixed", "all_matches_today"]:
                match_data = await get_team_match_data()
                matches = match_data.get("matches", [])
                
                # Détecter si un match est live
                self._has_live_match = self._check_for_live_matches(matches)
                
                if matches:
                    live_matches = [m for m in matches if m.get("state") == "in"]
                    if live_matches:
                        self._state = f"{live_matches[0]['home_score']} - {live_matches[0]['away_score']} ({live_matches[0]['clock']})"
                    else:
                        self._state = f"{len(matches)} partite per {match_data.get('team_name', 'N/A')}"
                else:
                    self._has_live_match = False
                    
                self._attributes = {
                    "league_info": match_data.get("league_info", "N/A"),
                    "team_name": match_data.get("team_name", "N/A"),
                    "team_logo": match_data.get("team_logo", "N/A"),
                    "matches": matches
                }
                
                _LOGGER.debug(f"{self._name}: Found {len(matches)} matches, live: {self._has_live_match}")

            elif self._sensor_type == "team_match":
                team_match = await get_team_match_data(next_match_only=True)
                matches = team_match.get("matches", [])
                
                # Détecter si un match est live
                self._has_live_match = self._check_for_live_matches(matches)
                
                if matches:
                    live_matches = [m for m in matches if m.get("state") == "in"]
                    if live_matches:
                        next_match = live_matches[0]
                        self._state = f"{next_match['home_score']} - {next_match['away_score']} ({next_match['clock']})"
                    else:
                        next_match = matches[0]
                        self._state = f"Prochain match: {next_match.get('home_team', 'N/A')} vs {next_match.get('away_team', 'N/A')}"
                    self._attributes = team_match
                else:
                    self._state = "Aucun match disponible"
                    self._attributes = team_match

