# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Home Assistant custom integration** (HACS-distributed) that tracks live NBA match data by polling ESPN's public APIs. It was forked from an Italian soccer integration ("Calcio Live"), so Italian variable names, comments, and module names (e.g., `sensori/classifica.py`) still appear throughout the code.

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
                                       NbaLiveSensor state + attributes
```

### Key Files

- [custom_components/nba_live/sensor.py](custom_components/nba_live/sensor.py) — Main sensor class (`NbaLiveSensor`). Handles polling, a per-URL cache shared by all sensors, and adaptive scan intervals (10s live, 10min idle).
- [custom_components/nba_live/config_flow.py](custom_components/nba_live/config_flow.py) — Multi-step UI config wizard. Dynamically fetches leagues and teams from ESPN at config time.
- [custom_components/nba_live/sensori/scoreboard.py](custom_components/nba_live/sensori/scoreboard.py) — Core data-processing engine. Transforms ESPN JSON into sensor attributes (scores, linescores, leaders, player stats, match events).
- [custom_components/nba_live/sensori/classifica.py](custom_components/nba_live/sensori/classifica.py) — Standings/classification data processing.
- [custom_components/nba_live/manifest.json](custom_components/nba_live/manifest.json) — HA integration metadata (domain: `nba_live`, min HA: 2024.8.0).

### Entry and Sensor Types

The config flow (menu, `VERSION = 2`) creates one of two entry types (`entry_type` in the entry data):
- `nba_team` (unique_id `team_<id>`) — sensors `next_match` and `schedule` (full season, all season types)
- `nba_league` (unique_id `nba_league`) — sensors `standings_east`, `standings_west` and `matches` (J-1 to J+4)

Sensor unique_ids are `<entry_id>_<key>`; `key` is also the entity `translation_key`. Entity ids keep the historical `nbalive_` prefix. `async_migrate_entry` in `__init__.py` converts version 1 entries (old Calcio Live modes) and their registry entities, keeping entity ids.

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

Localization strings live in `custom_components/nba_live/translations/`. Available: `en`, `it`, `fr`, `es`, `de` (no `strings.json`: custom integrations load `translations/<lang>.json` directly). Keys: config steps `user` (menu) and `nba_team`, aborts `already_configured`/`cannot_connect`, and `entity.sensor.<key>.name`.

## CI/CD

Two GitHub Actions workflows run on push, PR, and daily schedule:
- `hassfest` — validates `manifest.json` and integration structure against HA standards
- `hacs_action` — validates HACS compatibility (category: `integration`)

Both must pass before merging changes that touch `manifest.json` or `hacs.json`.
