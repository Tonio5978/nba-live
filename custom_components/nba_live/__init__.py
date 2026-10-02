import asyncio

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    _LOGGER,
    CONF_ENTRY_TYPE,
    CONF_TEAM_ID,
    CONF_TEAM_NAME,
    DOMAIN,
    ENTRY_TYPE_LEAGUE,
    ENTRY_TYPE_TEAM,
    LEAGUE_UNIQUE_ID,
    NBA_API_URL,
    team_unique_id,
)

PLATFORMS = ["sensor"]

# Version 1 : suffixe de l'ancien unique_id (f"{nom}_{sensor_type}") -> clé du
# capteur en version 2 (None = capteur supprimé). L'ordre compte : les
# suffixes les plus longs d'abord.
LEGACY_UNIQUE_ID_SUFFIXES = (
    ("_nba_team_next_match", "next_match"),
    ("_nba_team_schedule", "schedule"),
    ("_team_matches_mixed", None),
    ("_team_matches", "schedule"),
    ("_team_match", "next_match"),
    ("_east_standings", "standings_east"),
    ("_west_standings", "standings_west"),
    ("_match_day", "matches"),
    ("_all_matches_today", "matches"),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharge une entrée : permet de la recharger ou la supprimer sans redémarrer HA."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migre les entrées de l'ancien assistant (version 1, hérité de Calcio Live)."""
    if entry.version > 2:
        # Entrée créée par une version plus récente de l'intégration
        return False

    if entry.version == 1:
        data = await _async_migrate_v1_data(hass, entry)
        if data is None:
            _LOGGER.error(
                f"L'entrée « {entry.title} » utilise un mode qui n'existe plus "
                "(championnat ou équipe de football). Supprimez-la puis ajoutez "
                "à nouveau l'intégration NBA Live."
            )
            return False

        unique_id = (
            team_unique_id(data[CONF_TEAM_ID])
            if data[CONF_ENTRY_TYPE] == ENTRY_TYPE_TEAM
            else LEAGUE_UNIQUE_ID
        )
        # Doublon possible avec l'ancien assistant : l'entrée reste alors sans unique_id
        if any(
            other.unique_id == unique_id
            for other in hass.config_entries.async_entries(DOMAIN)
            if other.entry_id != entry.entry_id
        ):
            unique_id = None

        _migrate_v1_entities(hass, entry)
        hass.config_entries.async_update_entry(
            entry, data=data, options={}, unique_id=unique_id, version=2
        )
        _LOGGER.info(f"Entrée « {entry.title} » migrée en version 2")

    return True


async def _async_migrate_v1_data(hass, entry):
    """Convertit les données v1 ; None si le mode n'est pas convertible."""
    data = entry.data
    selection = data.get("selection")
    team_id = data.get("team_id")
    team_name = data.get("team_name")

    if selection in ("Championnat", "Tous les matchs de la journée"):
        # Ces modes créaient (ou tentaient de créer) les capteurs NBA de la ligue
        return {CONF_ENTRY_TYPE: ENTRY_TYPE_LEAGUE}

    if selection == "Equipe" and data.get("competition_code") == "nba" and not team_id and team_name:
        # L'ancien assistant ne retrouvait pas l'ID des équipes NBA : recherche par nom
        team_id = await _async_lookup_team_id(hass, team_name)

    if team_id and selection in ("Équipe NBA", "ID de l'équipe", "Equipe"):
        if selection == "Equipe" and data.get("competition_code") != "nba":
            return None
        return {
            CONF_ENTRY_TYPE: ENTRY_TYPE_TEAM,
            CONF_TEAM_ID: str(team_id),
            CONF_TEAM_NAME: team_name or f"Team {team_id}",
        }

    return None


async def _async_lookup_team_id(hass, team_name):
    """ID ESPN d'une équipe NBA à partir de son nom complet, ou None."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(f"{NBA_API_URL}/teams", timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            data = await response.json()
        teams = data["sports"][0]["leagues"][0]["teams"]
    except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, IndexError) as err:
        _LOGGER.error(f"Migration : impossible de récupérer les équipes NBA : {err}")
        return None
    return next(
        (str(t["team"]["id"]) for t in teams if t["team"]["displayName"].lower() == team_name.lower()),
        None,
    )


@callback
def _migrate_v1_entities(hass, entry):
    """Passe les unique_id des capteurs au format v2 en conservant leurs entity_id.

    Les capteurs sans équivalent en v2 sont supprimés du registre.
    """
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        key = next(
            (key for suffix, key in LEGACY_UNIQUE_ID_SUFFIXES if entity.unique_id.endswith(suffix)),
            None,
        )
        if key is None:
            _LOGGER.info(f"Migration : suppression de {entity.entity_id}, sans équivalent")
            registry.async_remove(entity.entity_id)
            continue
        new_unique_id = f"{entry.entry_id}_{key}"
        if entity.unique_id != new_unique_id:
            registry.async_update_entity(entity.entity_id, new_unique_id=new_unique_id)
