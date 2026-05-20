from .const import _LOGGER
from dateutil import parser
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone

# Helper function to check if team is TBD/unknown
def _is_team_valid(competitor):
    """
    Vérifie si un competitor est une vraie équipe ou TBD
    
    Returns:
        bool: True si équipe valide, False si TBD/-1/-2
    """
    if not competitor:
        return False
    
    team = competitor.get("team", {})
    team_id = str(team.get("id", ""))
    team_name = team.get("displayName", "")
    
    # Vérifier ID négatifs (TBD teams)
    if team_id in ["-1", "-2"]:
        return False
    
    # Vérifier noms TBD
    if "TBD" in team_name.upper():
        return False
    
    # Vérifier noms avec slash (équipes multiples)
    if "/" in team_name:
        return False
    
    return True


def _get_safe_team_data(competitor, default_name="TBD"):
    """
    Récupère les données d'équipe de manière sécurisée
    Retourne des valeurs par défaut si équipe TBD/invalide
    
    Args:
        competitor: Dictionnaire competitor
        default_name: Nom par défaut si équipe invalide
    
    Returns:
        dict: Données d'équipe sécurisées
    """
    if not _is_team_valid(competitor):
        return {
            "team_name": default_name,
            "abbreviation": "N/A",
            "logo": None,
            "score": "0",
            "form": "N/A",
            "linescores": [],
            "statistics": {},
            "leaders": {},
            "records": {
                "overall": "",
                "home": "",
                "road": ""
            }
        }
    
    # Équipe valide - récupération normale (sera appelée après définition des fonctions helper)
    team_data = competitor.get("team", {})
    
    # Récupérer logo
    logo = team_data.get("logo", None)
    if not logo:
        logos = team_data.get("logos", [{}])
        logo = logos[0].get("href", "N/A") if logos else "N/A"
    
    # Récupérer records de manière sécurisée
    records_list = competitor.get("records", [])
    records = {
        "overall": records_list[0].get("summary", "") if len(records_list) > 0 else "",
        "home": records_list[1].get("summary", "") if len(records_list) > 1 else "",
        "road": records_list[2].get("summary", "") if len(records_list) > 2 else ""
    }
    
    return {
        "team_name": team_data.get("displayName", "N/A"),
        "abbreviation": team_data.get("abbreviation", "N/A"),
        "logo": logo,
        "score": competitor.get("score", "0"),
        "form": competitor.get("form", "N/A"),
        "linescores": [],  # Rempli après
        "statistics": {},  # Rempli après
        "leaders": {},     # Rempli après
        "records": records
    }

def process_league_data(data, hass=None):
    try:
        leagues_data = data.get("leagues", [])
        league_info = []

        for league in leagues_data:
            league_abbreviation = league.get("abbreviation", "N/A")
            league_start_date = league.get("season", {}).get("startDate", "N/A")
            league_end_date = league.get("season", {}).get("endDate", "N/A")
            
            logos = league.get("logos", [])
            logo_href = logos[0].get("href", "N/A") if logos else "N/A"
            
            league_info.append({
                "abbreviation": league_abbreviation,
                "startDate": _parse_date(hass, league_start_date, show_time=False),
                "endDate": _parse_date(hass, league_end_date, show_time=False),
                "logo_href": logo_href
            })

        return league_info

    except Exception as e:
        _LOGGER.error(f"Errore nel processare i dati della lega: {e}")
        return []

def get_season_slug_or_displayname(match):
    season_data = match.get("season", {})
    
    # Controlla prima per 'slug', se esiste
    slug = season_data.get("slug")
    if slug:
        return slug
    
    # Se non trova 'slug', prova a prendere 'displayName'
    display_name = season_data.get("displayName")
    return display_name
    
async def process_match_data(data, hass, team_name=None, next_match_only=False, start_date=None, end_date=None):
    try:
        matches_data = data.get("events", [])
        league_info = process_league_data(data, hass)
        matches = []
        scores = []
        team_logo = None

        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        for match in matches_data:
            match_name = match.get("name", "").lower()
            if team_name and team_name.lower() not in match_name:
                continue

            match_date_str = match.get("date", "")
            match_id = match.get("id", "")
            try:
                match_date = parser.isoparse(match_date_str).astimezone(timezone.utc) if match_date_str else None
            except ValueError:
                _LOGGER.error(f"Errore nel parsing della data della partita: {match_date_str}")
                continue

            if start_date and match_date and match_date < start_date:
                continue
            if end_date and match_date and match_date > end_date:
                continue
            
            #Solo per il mixed
            season_info = get_season_slug_or_displayname(match)

            competitions = match.get("competitions", [])
            
            # Vérifier que competitions n'est pas vide
            if not competitions or len(competitions) == 0:
                _LOGGER.warning(f"Match {match_id}: Pas de competitions, skipping")
                continue
            
            competitors = competitions[0].get("competitors", [])
            
            # Vérifier qu'on a exactement 2 competitors
            if len(competitors) != 2:
                _LOGGER.warning(f"Match {match_id}: {len(competitors)} competitors (attendu: 2), skipping")
                continue
            
            # Récupération sécurisée des données HOME team
            home_data = _get_safe_team_data(competitors[0], "TBD Home")
            home_team = home_data["team_name"]
            home_logo = home_data["logo"]
            home_form = home_data["form"]
            home_score = home_data["score"]
            home_linescores = _get_linescores(competitors[0]) if _is_team_valid(competitors[0]) else []
            home_statistics = _get_statistics(competitors[0]) if _is_team_valid(competitors[0]) else {}
            home_leaders = _get_leaders(competitors[0]) if _is_team_valid(competitors[0]) else {}
            home_overall = home_data["records"]["overall"]
            home_home = home_data["records"]["home"]
            home_road = home_data["records"]["road"]
            
            # Récupération sécurisée des données AWAY team
            away_data = _get_safe_team_data(competitors[1], "TBD Away")
            away_team = away_data["team_name"]
            
            # Log si équipes TBD détectées
            if not _is_team_valid(competitors[0]) or not _is_team_valid(competitors[1]):
                _LOGGER.info(f"Match {match_id}: {away_team} @ {home_team} - Équipe(s) TBD/non déterminée(s)")

            away_logo = away_data["logo"]
            away_form = away_data["form"]
            away_score = away_data["score"]
            away_linescores = _get_linescores(competitors[1]) if _is_team_valid(competitors[1]) else []
            away_statistics = _get_statistics(competitors[1]) if _is_team_valid(competitors[1]) else {}
            away_leaders = _get_leaders(competitors[1]) if _is_team_valid(competitors[1]) else {}
            away_overall = away_data["records"]["overall"]
            away_home = away_data["records"]["home"]
            away_road = away_data["records"]["road"]

            status_type = match.get("status", {}).get("type", {})
            match_state = status_type.get("state", "N/A")
            match_status = status_type.get("description", "N/A")
            clock = match.get("status", {}).get("displayClock", "N/A")
            period = match.get("status", {}).get("period", "N/A")
            venue = competitions[0].get("venue", {}).get("fullName", "N/A")
            match_details = _get_details(competitions[0].get("details", []))
            
            # Récupérer les statistiques détaillées des joueurs si le match est terminé (ASYNC)
            player_stats = await _get_player_stats(hass, match_id, match_state) if match_state == "post" else None

            if team_name and (team_name.lower() in home_team.lower() or team_name.lower() in away_team.lower()):
                team_logo = home_logo if team_name.lower() in home_team.lower() else away_logo

            match_data = {
                "date": _parse_date(hass, match.get("date")),
                "match_id": match_id,
                "season_info": season_info, #per il mixed
                "home_team": home_team,
                "home_logo": home_logo,
                "home_form": home_form,
                "home_score": home_score,
                "home_linescores": home_linescores,
                #"home_period1": home_period1,
                "home_statistics": home_statistics,
                "home_leaders": home_leaders,  # Leaders complets (points, rebounds, assists)
                "home_overall": home_overall,
                "home_home": home_home,
                "home_road": home_road,
                "away_team": away_team,
                "away_logo": away_logo,
                "away_form": away_form,
                "away_score": away_score,
                "away_linescores": away_linescores,
                #"home_period0": append(f"{home_linescores[0]} - {away_linescores[0]}"),
                #"home_period0": scores[0],
                "away_statistics": away_statistics,
                "away_leaders": away_leaders,  # Leaders complets (points, rebounds, assists)
                "away_overall": away_overall,
                "away_home": away_home,
                "away_road": away_road,

                "state": match_state,
                "status": match_status,
                "clock": clock,
                "period": period,
                "venue": venue,
                "match_details": match_details,
                
                # Statistiques détaillées des joueurs (uniquement si match terminé)
                "player_stats": player_stats,
            }
            matches.append(match_data)

        if next_match_only:
            # Priorità 1: Partite in corso
            live_matches = [m for m in matches if m["state"] == "in"]
            if live_matches:
                return {
                    "league_info": league_info,
                    "team_name": team_name if team_name else "Tutte le partite",
                    "team_logo": team_logo if team_logo else "N/A",
                    "matches": [live_matches[0]]
                }

            # Priorità 2: Partite terminate entro 48 ore
            recent_finished_matches = [m for m in matches
                if m["state"] == "post" and is_within_last_48_hours(m["date"])
            ]
            
            if recent_finished_matches:
                return {
                    "league_info": league_info,
                    "team_name": team_name if team_name else "Tutte le partite",
                    "team_logo": team_logo if team_logo else "N/A",
                    "matches": [recent_finished_matches[0]]
                }

            # Priorità 3: Prossime partite
            upcoming_matches = [m for m in matches if m["state"] == "pre"]
            if upcoming_matches:
                return {
                    "league_info": league_info,
                    "team_name": team_name if team_name else "Tutte le partite",
                    "team_logo": team_logo if team_logo else "N/A",
                    "matches": [upcoming_matches[0]]
                }
                
        return {
            "league_info": league_info,
            "team_name": team_name if team_name else "Tutte le partite",
            "team_logo": team_logo if team_logo else "N/A",
            "matches": matches
        }

    except Exception as e:
        _LOGGER.error(f"Errore nel processare i dati delle partite: {e}")
        return {}

def is_within_last_48_hours(end_time):
    try:
        # Converte la stringa formattata in oggetto datetime
        if isinstance(end_time, str):
            end_time_dt = datetime.strptime(end_time, "%d/%m/%Y %H:%M").replace(tzinfo=timezone.utc)
        elif isinstance(end_time, datetime):
            end_time_dt = end_time
        else:
            raise ValueError("La data fornita non è né una stringa né un oggetto datetime")
        
        # Ottiene l'orario attuale con timezone UTC
        current_time = datetime.now(timezone.utc)
        
        # Confronta l'intervallo di 48 ore
        return current_time - end_time_dt <= timedelta(hours=48)
    except Exception as e:
        _LOGGER.error(f"Errore nel calcolo dell'intervallo di 48 ore: {e}")
        return False

def _get_statistics(competitor):
    statistics = {}
    stats = competitor.get("statistics", [])
    for stat in stats:
        stat_name = stat.get("name", "Unknown")
        stat_value = stat.get("displayValue", "N/A")
        statistics[stat_name] = stat_value
    return statistics

def _get_leaders(competitor):
    """
    Extrait tous les leaders (points, rebounds, assists) d'un competitor
    Retourne un dictionnaire avec les meilleurs joueurs pour chaque catégorie
    """
    leaders_data = {}
    leaders = competitor.get("leaders", [])
    
    for leader_category in leaders:
        # Nom de la catégorie (ex: "points", "rebounds", "assists")
        category_name = leader_category.get("name", "").lower()
        category_display = leader_category.get("displayName", category_name)
        
        # Récupérer le premier leader (meilleur joueur)
        leaders_list = leader_category.get("leaders", [])
        if leaders_list:
            top_leader = leaders_list[0]
            
            athlete = top_leader.get("athlete", {})
            player_name = athlete.get("displayName", "N/A")
            player_headshot = athlete.get("headshot", "")
            
            # Valeur de la stat
            stat_value = top_leader.get("displayValue", "N/A")
            stat_raw_value = top_leader.get("value", 0)
            
            leaders_data[category_name] = {
                "player": player_name,
                "value": stat_value,
                "raw_value": stat_raw_value,
                "headshot": player_headshot,
                "category": category_display
            }
    
    return leaders_data


async def _get_player_stats(hass, match_id, match_state):
    """
    Récupère les statistiques détaillées de tous les joueurs pour un match terminé
    Via l'API ESPN Summary (ASYNC)
    
    Args:
        hass: Home Assistant instance (pour utiliser async_add_executor_job)
        match_id (str): ID du match
        match_state (str): État du match ("post" pour terminé)
    
    Returns:
        dict: Statistiques des joueurs par équipe ou None si non disponible
    """
    
    # Ne récupérer que si le match est terminé
    if match_state != "post":
        return None
    
    try:
        # URL de l'API Summary ESPN
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={match_id}"
        
        _LOGGER.debug(f"Fetching player stats for match {match_id} from {url}")
        
        # Utiliser aiohttp depuis Home Assistant
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                data = await response.json()
        
        # Extraire les statistiques des box scores
        boxscore = data.get("boxscore", {})
        players = boxscore.get("players", [])
        
        if not players or len(players) < 2:
            _LOGGER.warning(f"No player stats found for match {match_id}")
            return None
        
        # Structure: players[0] = équipe 1, players[1] = équipe 2
        home_stats = _parse_team_player_stats(players[0])
        away_stats = _parse_team_player_stats(players[1])
        
        return {
            "home_players": home_stats,
            "away_players": away_stats,
            "has_detailed_stats": True
        }
        
    except aiohttp.ClientError as e:
        _LOGGER.error(f"Error fetching player stats for match {match_id}: {e}")
        return None
    except Exception as e:
        _LOGGER.error(f"Error parsing player stats for match {match_id}: {e}")
        return None


def _parse_team_player_stats(team_data):
    """
    Parse les statistiques des joueurs d'une équipe
    
    Args:
        team_data (dict): Données d'une équipe depuis l'API summary
    
    Returns:
        dict: Dictionnaire avec team info et liste des joueurs
    """
    
    players_stats = []
    
    # Informations de l'équipe
    team_info = team_data.get("team", {})
    team_name = team_info.get("displayName", "N/A")
    team_abbreviation = team_info.get("abbreviation", "N/A")
    
    # Statistiques des joueurs
    statistics = team_data.get("statistics", [])
    
    _LOGGER.debug(f"Team {team_name}: found {len(statistics)} statistics groups")
    
    # Parser tous les groupes de statistiques qui contiennent des athlètes
    for stat_group in statistics:
        stat_name = stat_group.get("name", "")
        athletes = stat_group.get("athletes", [])
        
        _LOGGER.debug(f"  Group '{stat_name}': {len(athletes)} athletes")
        
        # Si le groupe contient des athlètes, on les traite
        # (au lieu de filtrer par nom exact, on accepte tout ce qui a des données)
        if athletes and len(athletes) > 0:
            for athlete_data in athletes:
                athlete = athlete_data.get("athlete", {})
                stats = athlete_data.get("stats", [])
                
                # Informations du joueur
                player_name = athlete.get("displayName", "N/A")
                player_id = athlete.get("id", "")
                player_position = athlete.get("position", {}).get("abbreviation", "N/A")
                player_jersey = athlete.get("jersey", "N/A")
                player_headshot = athlete.get("headshot", {}).get("href", "")
                
                # Convertir les stats en dictionnaire
                player_stats = {}
                
                # Les stats sont dans l'ordre:
                # MIN, FG, 3PT, FT, OREB, DREB, REB, AST, STL, BLK, TO, PF, +/-, PTS
                stat_labels = [
                    "minutes", "fg", "3pt", "ft", "oreb", "dreb", "reb", 
                    "ast", "stl", "blk", "to", "pf", "plusMinus", "pts"
                ]
                
                for i, stat_value in enumerate(stats):
                    if i < len(stat_labels):
                        player_stats[stat_labels[i]] = stat_value
                
                # Déterminer si titulaire (starters) ou remplaçant (bench)
                is_starter = stat_name.lower() in ["starters", "starter"]
                
                # Ajouter le joueur à la liste
                players_stats.append({
                    "name": player_name,
                    "id": player_id,
                    "position": player_position,
                    "jersey": player_jersey,
                    "headshot": player_headshot,
                    "stats": player_stats,
                    "starter": is_starter
                })
                
                _LOGGER.debug(f"    Added player: {player_name} - {len(stats)} stats")
    
    _LOGGER.debug(f"Total players parsed for {team_name}: {len(players_stats)}")
    
    return {
        "team_name": team_name,
        "team_abbreviation": team_abbreviation,
        "players": players_stats
    }

def _get_linescores(competitor):
    linescores = []
    stats = competitor.get("linescores", [])
    for line_score in stats:
            linescores.append(str(line_score["value"]))
    return linescores

def _get_details(details):
    events = []
    for detail in details:
        event_type = detail.get("type", {}).get("text", "Unknown")
        clock = detail.get("clock", {}).get("displayValue", "N/A")
        athletes = [athlete.get("displayName", "Unknown") for athlete in detail.get("athletesInvolved", [])]
        athletes_str = ", ".join(athletes) if athletes else "N/A"
        events.append(f"{event_type} - {clock}: {athletes_str}")
    return events

def _parse_date(hass, date_str, show_time=True):
    try:
        user_timezone = hass.config.time_zone
        parsed_date = parser.isoparse(date_str).replace(tzinfo=timezone.utc)
        local_tz = ZoneInfo(user_timezone)
        local_date = parsed_date.astimezone(local_tz)

        if show_time:
            return local_date.strftime("%d/%m/%Y %H:%M")
        else:
            return local_date.strftime("%d/%m/%Y")
    except (ValueError, TypeError) as e:
        #_LOGGER.error(f"Errore nel parsing della data {date_str}: {e}")
        return "N/A"