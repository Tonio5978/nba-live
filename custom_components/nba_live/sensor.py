import asyncio
import aiohttp
from datetime import datetime, timedelta
from homeassistant.helpers.entity import Entity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import random
from .const import DOMAIN, _LOGGER

# Intervalles de mise à jour
SCAN_INTERVAL_LIVE = timedelta(seconds=10)     # Match en cours
SCAN_INTERVAL_IDLE = timedelta(minutes=10)     # Pas de match en cours
SCAN_INTERVAL = SCAN_INTERVAL_IDLE  # Par défaut

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
    
        if team_name:
            team_name_normalized = team_name.replace(" ", "_").replace(".", "_").lower()
            competition_name = competition_code.replace(" ", "_").replace(".", "_").lower()

            sensors += [
                CalcioLiveSensor(
                    hass, f"calciolive_next_{competition_name}_{team_name_normalized}", competition_code, "team_match",
                    base_scan_interval + timedelta(seconds=random.randint(0, 30)), team_name=team_name,
                    config_entry_id=entry.entry_id, start_date=start_date, end_date=end_date, team_id=team_id
                ),
                CalcioLiveSensor(
                    hass, f"calciolive_all_{competition_name}_{team_name_normalized}", competition_code, "team_matches",
                    base_scan_interval + timedelta(seconds=random.randint(0, 30)), team_name=team_name,
                    config_entry_id=entry.entry_id, start_date=start_date, end_date=end_date, team_id=team_id
                ),
                CalcioLiveSensor(
                    hass, f"calciolive_all_mixed_{team_name_normalized}", competition_code, "team_matches_mixed",
                    base_scan_interval + timedelta(seconds=random.randint(0, 30)), team_name=team_name,
                    config_entry_id=entry.entry_id, start_date=start_date, end_date=end_date, team_id=team_id
                )
            ]
        elif competition_code:
            if competition_code == "99999":  # Se il competition_code è fittizio, crea il sensore per tutte le partite
                sensors += [
                    CalcioLiveSensor(
                        hass, "calciolive_all_today", competition_code, "all_matches_today",
                        base_scan_interval + timedelta(seconds=random.randint(0, 30)), config_entry_id=entry.entry_id,
                        start_date=start_date, end_date=end_date, team_id=team_id
                    )
                ]
            else:
                competition_name = competition_name.replace(" ", "_").replace(".", "_").lower()

                sensors += [
                    #CalcioLiveSensor(
                    #    hass, f"calciolive_classifica_{competition_name}", competition_code, "standings",
                    #    base_scan_interval + timedelta(seconds=random.randint(0, 30)), config_entry_id=entry.entry_id,
                    #    start_date=start_date, end_date=end_date, team_id=team_id
                    #),
                    CalcioLiveSensor(
                        hass, f"calciolive_all_nba", competition_code, "match_day",
                        base_scan_interval + timedelta(seconds=random.randint(0, 30)), config_entry_id=entry.entry_id,
                        start_date=start_date, end_date=end_date, team_id=team_id
                    )
                ]

        async_add_entities(sensors, True)

    except Exception as e:
        _LOGGER.error(f"Errore durante la configurazione dei sensori: {e}")


class CalcioLiveSensor(Entity):
    _cache = {}

    def __init__(self, hass, name, code, sensor_type=None, scan_interval=timedelta(seconds=5),
                 team_name=None, config_entry_id=None, start_date=None, end_date=None, team_id=None):
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
        
        for match in matches_data:
            match_state = match.get("match_state", "").lower()
            status = match.get("status", "").lower()
            
            # Vérifier si le match est en cours
            if match_state == "in" or "live" in status or "in progress" in status:
                return True
        
        return False

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
            if time_since_update < update_interval:
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

        cache_key = f"{self._sensor_type}_{self._code}_{self._team_name}"
        if cache_key in CalcioLiveSensor._cache and (datetime.now() - CalcioLiveSensor._cache[cache_key]["time"]).seconds < 10:
            await self._process_data(CalcioLiveSensor._cache[cache_key]["data"])
            _LOGGER.info(f"Using cached data for {self._name}")
            self._last_update_time = now
            return

        url = await self._build_url()
        _LOGGER.debug(f"url asked : {url}")
        if url is None:
            self._last_update_time = now
            return

        retries = 0
        while retries < 3:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            _LOGGER.debug(f"Data received for {self._name}: {data}")
                            CalcioLiveSensor._cache[cache_key] = {"data": data, "time": datetime.now()}
                            await self._process_data(data)
                            self._last_update_time = now
                            _LOGGER.info(f"Finished update for {self._name}")
                            break
                        else:
                            await asyncio.sleep(5)
                            retries += 1
            except aiohttp.ClientError as error:
                await asyncio.sleep(5)
                retries += 1
            except asyncio.TimeoutError:
                await asyncio.sleep(5)
                retries += 1
        
        # Mettre à jour le timestamp même en cas d'erreur
        if self._last_update_time is None:
            self._last_update_time = now

    
    async def _build_url(self):
        base_url    = "https://site.web.api.espn.com/apis/v2/sports/soccer"
        base_url_2  = "https://site.api.espn.com/apis/site/v2/sports/basketball"  #"https://site.api.espn.com/apis/site/v2/sports/soccer"
        base_url_3  = "https://site.web.api.espn.com/apis/site/v2/sports/soccer"
        season_data = ""
        season_start = ""
        season_end = ""
    
      #  if self._code:
      #      season_start, season_end = await self._get_calendar_data()

        # Se le date non sono state recuperate, utilizza quelle di default
        if not season_start or not season_end:
            season_start = self._start_date.strftime("%Y-%m-%d")
            season_end = self._end_date.strftime("%Y-%m-%d")
    
        start_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = start_date[:10].replace("-", "")
        _LOGGER.debug(f"start date asked : {start_date}")

        end_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
        end_date = end_date[:10].replace("-", "")
        _LOGGER.debug(f"end date asked : {end_date}")

        season_start = season_start[:10].replace("-", "")
        season_end = season_end[:10].replace("-", "")
    
        standings_url = f"{self.base_url}/{self._code}/standings?"
        scoreboard_url = f"{self.base_url_2}/nba/scoreboard?limit=25&dates={start_date}-{end_date}"
        all_matches_today_url = f"{self.base_url_2}/all/scoreboard"
        team_url_schedule_mixed = f"{self.base_url_3}/all/teams/{self._team_id}/schedule?fixture=true"
    
        if self._sensor_type == "standings":
            return standings_url
        elif self._sensor_type in ("match_day", "team_match", "team_matches"):
            return scoreboard_url
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
            processed_data = classifica_data(data)
            self._state = "Classifica"
            self._attributes = processed_data
            self._has_live_match = False  # Pas de live pour standings

        elif self._sensor_type == "match_day":
            match_data = await process_match_data(data, self.hass, start_date=self._start_date.strftime("%Y-%m-%d"), end_date=self._end_date.strftime("%Y-%m-%d"))
            matches = match_data.get("matches", [])
            
            # Détecter si un match est live
            self._has_live_match = self._check_for_live_matches(matches)
            
            self._state = "Matches of the Week"
            self._attributes = {
                "league_info": match_data.get("league_info", "N/A"),
                "matches": matches
            }
            
            _LOGGER.debug(f"{self._name}: Found {len(matches)} matches, {sum(1 for m in matches if m.get('match_state') == 'in')} live")
        
        elif self._sensor_type in ["team_matches", "team_match", "team_matches_mixed", "all_matches_today"]:
            async def get_team_match_data(next_match_only=False):
                return await process_match_data(
                    data, self.hass, team_name=self._team_name, next_match_only=next_match_only,
                    start_date=self._start_date.strftime("%Y-%m-%d"), end_date=self._end_date.strftime("%Y-%m-%d")
                )

            if self._sensor_type in ["team_matches", "team_matches_mixed", "all_matches_today"]:
                match_data = await get_team_match_data()
                matches = match_data.get("matches", [])
                
                # Détecter si un match est live
                self._has_live_match = self._check_for_live_matches(matches)
                
                if matches:
                    live_matches = [m for m in matches if m.get("match_state") == "in"]
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
                    live_matches = [m for m in matches if m.get("match_state") == "in"]
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

