# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Home Assistant custom integration** (HACS-distributed) that tracks live NBA match data by polling ESPN's public APIs. It was forked from an Italian soccer integration ("Calcio Live"), so Italian variable names, comments, and class names (e.g., `CalcioLiveSensor`) still appear throughout the code.

## Development Setup

No local build step is required. The integration runs directly inside a Home Assistant instance. For development and validation:

```bash
# Install Python dependencies locally (for linting/testing)
pip install arrow aiofiles pytz==2023.3

# Validate the integration against Home Assistant standards (CI does this automatically)
# See .github/workflows/hassfest.yaml

# HACS validation
# See .github/workflows/hacs_action.yaml
```

Deploying changes: copy `custom_components/nba_live/` into a Home Assistant instance's `custom_components/` directory and restart.

## Architecture

### Data Flow

```
HA Config UI → config_flow.py → ConfigEntry
                                     ↓
              __init__.py (async_setup_entry) → sensor.py
                                                     ↓
                                    ESPN APIs (basketball/soccer)
                                                     ↓
                              sensori/scoreboard.py (data processing)
                              sensori/classifica.py (standings)
                                                     ↓
                                       CalcioLiveSensor state + attributes
```

### Key Files

- [custom_components/nba_live/sensor.py](custom_components/nba_live/sensor.py) — Main sensor class (`CalcioLiveSensor`). Handles polling, caching (10s TTL), and adaptive scan intervals (10s live, 10min idle).
- [custom_components/nba_live/config_flow.py](custom_components/nba_live/config_flow.py) — Multi-step UI config wizard. Dynamically fetches leagues and teams from ESPN at config time.
- [custom_components/nba_live/sensori/scoreboard.py](custom_components/nba_live/sensori/scoreboard.py) — Core data-processing engine. Transforms ESPN JSON into sensor attributes (scores, linescores, leaders, player stats, match events).
- [custom_components/nba_live/sensori/classifica.py](custom_components/nba_live/sensori/classifica.py) — Standings/classification data processing.
- [custom_components/nba_live/manifest.json](custom_components/nba_live/manifest.json) — HA integration metadata (domain: `nba_live`, min HA: 2024.8.0).

### Sensor Types

Configured via `sensor_type` in the config entry:
- `match_day` — All matches in a date range
- `team_match` — Next upcoming match for a team
- `team_matches` — All matches for a team
- `team_matches_mixed` — Cross-league matches
- `standings` — League standings
- `all_matches_today` — All matches across all sports today

### ESPN API Endpoints

- Basketball (primary): `https://site.api.espn.com/apis/site/v2/sports/basketball/{league}/`
- Soccer (legacy/fallback): `https://site.web.api.espn.com/apis/v2/sports/soccer/{league}/`

No authentication is required.

### Adaptive Polling

`sensor.py` switches between two intervals at runtime based on whether any match is currently live:
- `SCAN_INTERVAL_LIVE = timedelta(seconds=10)`
- `SCAN_INTERVAL_IDLE = timedelta(minutes=10)`

A ±30-second random jitter is applied to distribute API load.

### Translations

Localization strings live in `custom_components/nba_live/translations/`. Available: `en` (strings.json), `it`, `fr`, `es`, `de`. Config flow step IDs that need translations: `user`, `campionato`, `team`, `manual_team`, `dates`.

## CI/CD

Two GitHub Actions workflows run on push, PR, and daily schedule:
- `hassfest` — validates `manifest.json` and integration structure against HA standards
- `hacs_action` — validates HACS compatibility (category: `integration`)

Both must pass before merging changes that touch `manifest.json` or `hacs.json`.
