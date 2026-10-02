import asyncio

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

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


class NbaLiveConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configuration : suivre une équipe NBA, ou la ligue (classements + matchs)."""

    VERSION = 2

    def __init__(self):
        self._teams = {}

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(
            step_id="user",
            menu_options=[ENTRY_TYPE_TEAM, ENTRY_TYPE_LEAGUE],
        )

    async def async_step_nba_team(self, user_input=None):
        if user_input is not None:
            team_id = user_input[CONF_TEAM_ID]
            team_name = self._teams.get(team_id, f"Team {team_id}")

            await self.async_set_unique_id(team_unique_id(team_id))
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"NBA {team_name}",
                data={
                    CONF_ENTRY_TYPE: ENTRY_TYPE_TEAM,
                    CONF_TEAM_ID: team_id,
                    CONF_TEAM_NAME: team_name,
                },
            )

        try:
            self._teams = await self._async_get_nba_teams()
        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, IndexError) as err:
            _LOGGER.error(f"Erreur lors du chargement des équipes NBA : {err}")
            return self.async_abort(reason="cannot_connect")
        if not self._teams:
            return self.async_abort(reason="cannot_connect")

        options = [
            SelectOptionDict(value=team_id, label=name)
            for team_id, name in sorted(self._teams.items(), key=lambda item: item[1])
        ]
        return self.async_show_form(
            step_id="nba_team",
            data_schema=vol.Schema({
                vol.Required(CONF_TEAM_ID): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
                ),
            }),
        )

    async def async_step_nba_league(self, user_input=None):
        await self.async_set_unique_id(LEAGUE_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="NBA", data={CONF_ENTRY_TYPE: ENTRY_TYPE_LEAGUE})

    async def _async_get_nba_teams(self):
        """Retourne {team_id: nom complet} des équipes NBA."""
        session = async_get_clientsession(self.hass)
        async with session.get(f"{NBA_API_URL}/teams", timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            data = await response.json()
        teams = data["sports"][0]["leagues"][0]["teams"]
        return {str(t["team"]["id"]): t["team"]["displayName"] for t in teams}
