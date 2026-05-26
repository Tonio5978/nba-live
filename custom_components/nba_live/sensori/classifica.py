from .const import _LOGGER
from dateutil import parser

def classifica_data(data, conference=None):
    try:
        children = data.get("children", [])

        if conference:
            children = [c for c in children if c.get("abbreviation") == conference]

        standings_list = []

        for child in children:
            entries = child.get("standings", {}).get("entries", [])
            season_display_name = child.get("standings", {}).get("seasonDisplayName", "N/A")
            standings = []

            for index, entry in enumerate(entries, start=1):
                team = entry.get("team", {})
                stats = {s["name"]: s["displayValue"] for s in entry.get("stats", [])}

                team_data = {
                    "rank": index,
                    "team_id": team.get("id"),
                    "team_name": team.get("displayName"),
                    "team_abbreviation": team.get("abbreviation"),
                    "team_logo": team.get("logos", [{}])[0].get("href"),
                    "overall": stats.get("overall", "N/A"),
                    "wins": stats.get("wins", "N/A"),
                    "losses": stats.get("losses", "N/A"),
                    "win_pct": stats.get("winPercent", "N/A"),
                    "games_behind": stats.get("gamesBehind", "N/A"),
                    "home": stats.get("Home", "N/A"),
                    "road": stats.get("Road", "N/A"),
                    "differential": stats.get("differential", "N/A"),
                    "streak": stats.get("streak", "N/A"),
                    "last_ten": stats.get("Last Ten Games", "N/A"),
                    "playoff_seed": stats.get("playoffSeed", "N/A"),
                    "clincher": stats.get("clincher", ""),
                }
                standings.append(team_data)

            standings_list.append({
                "conference": child.get("name", "Unknown"),
                "abbreviation": child.get("abbreviation", ""),
                "season": season_display_name,
                "standings": standings,
            })

        if conference and standings_list:
            return {
                "season": standings_list[0]["season"],
                "conference": standings_list[0]["conference"],
                "abbreviation": standings_list[0]["abbreviation"],
                "standings": standings_list[0]["standings"],
            }

        return {
            "standings_groups": standings_list,
        }

    except Exception as e:
        _LOGGER.error(f"Errore nel processare i dati della classifica: {e}")
        return {}
