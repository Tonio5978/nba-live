from .const import _LOGGER
from .scoreboard import _get_leaders, _parse_date, _get_player_stats, _get_linescores, _parse_iso_utc
from datetime import datetime, timezone


async def process_nba_team_schedule(data, hass, start_date=None, end_date=None):
    try:
        team_info = data.get("team", {})
        team_name = team_info.get("displayName", "N/A")
        logos = team_info.get("logos", [])
        team_logo = logos[0].get("href") if logos else None

        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        matches = []

        for event in data.get("events", []):
            match_date_str = event.get("date", "")
            match_id = event.get("id", "")

            try:
                match_date = _parse_iso_utc(match_date_str) if match_date_str else None
            except ValueError:
                continue

            if start_date and match_date and match_date < start_date:
                continue
            if end_date and match_date and match_date > end_date:
                continue

            competitions = event.get("competitions", [])
            if not competitions:
                continue
            comp = competitions[0]

            competitors = comp.get("competitors", [])
            if len(competitors) != 2:
                continue

            home_comp = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
            away_comp = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

            # Status lives at competition level (different from scoreboard where it's at event level)
            status = comp.get("status", {})
            status_type = status.get("type", {})
            match_state = status_type.get("state", "N/A")
            match_status = status_type.get("description", "N/A")
            clock = status.get("displayClock", "N/A")
            period = status.get("period", "N/A")
            venue = comp.get("venue", {}).get("fullName", "N/A")

            series_summary = comp.get("series", {}).get("summary", None)

            player_stats = await _get_player_stats(hass, match_id, match_state, match_date) if match_state == "post" else None

            matches.append({
                "date": _parse_date(hass, match_date_str),
                "match_id": match_id,
                "home_team": home_comp.get("team", {}).get("displayName", "N/A"),
                "home_logo": _get_team_logo(home_comp),
                "home_score": _get_score(home_comp),
                "home_record": _get_record(home_comp),
                "home_linescores": _get_linescores(home_comp),
                "home_leaders": _get_leaders(home_comp),
                "away_team": away_comp.get("team", {}).get("displayName", "N/A"),
                "away_logo": _get_team_logo(away_comp),
                "away_score": _get_score(away_comp),
                "away_record": _get_record(away_comp),
                "away_linescores": _get_linescores(away_comp),
                "away_leaders": _get_leaders(away_comp),
                "state": match_state,
                "status": match_status,
                "clock": clock,
                "period": period,
                "venue": venue,
                "series_summary": series_summary,
                "player_stats": player_stats,
            })

        return {
            "team_name": team_name,
            "team_logo": team_logo,
            "matches": matches,
        }

    except Exception as e:
        _LOGGER.error(f"Error processing NBA team schedule: {e}")
        return {}


def _get_score(competitor):
    score = competitor.get("score", {})
    if isinstance(score, dict):
        return score.get("displayValue", "0")
    return str(score)


def _get_record(competitor):
    # 'record' (singular) in schedule API — index 0 is overall season record
    records = competitor.get("record", [])
    return records[0].get("displayValue", "") if records else ""


def _get_team_logo(competitor):
    logos = competitor.get("team", {}).get("logos", [])
    return logos[0].get("href") if logos else None
