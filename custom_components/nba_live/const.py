import logging
_LOGGER = logging.getLogger(__name__)

DOMAIN = "nba_live"

NBA_API_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"

# Données d'une entrée de configuration
CONF_ENTRY_TYPE = "entry_type"
CONF_TEAM_ID = "team_id"
CONF_TEAM_NAME = "team_name"

# Types d'entrée (= options du menu de configuration)
ENTRY_TYPE_TEAM = "nba_team"
ENTRY_TYPE_LEAGUE = "nba_league"

LEAGUE_UNIQUE_ID = "nba_league"


def team_unique_id(team_id):
    """unique_id d'une entrée « équipe » : une seule entrée par équipe."""
    return f"team_{team_id}"
