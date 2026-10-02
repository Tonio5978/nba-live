# NBA Live - Intégration Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![PayPal](https://img.shields.io/badge/Donate-PayPal-%2300457C?style=for-the-badge&logo=paypal&logoColor=white)](https://www.paypal.com/donate/?hosted_button_id=Z6KY9V6BBZ4BN)

## Description

**NBA Live** est une intégration personnalisée pour Home Assistant permettant de suivre en temps réel les matchs NBA. Elle s'appuie sur l'API publique d'ESPN (aucune clé API requise) et crée des capteurs automatiquement mis à jour :

- **10 secondes** lorsqu'un match est en cours
- **10 minutes** lorsqu'aucun match n'est actif

## Installation via HACS

1. Dans HACS, cliquez sur **"Dépôts personnalisés"** et ajoutez :
   ```
   https://github.com/Tonio5978/nba-live
   ```
   en choisissant la catégorie **Intégration**.

2. Recherchez **"NBA Live"** dans HACS et installez l'intégration.

3. Redémarrez Home Assistant.

4. Allez dans **Paramètres › Appareils et services › Ajouter une intégration** et recherchez `NBA Live`.

## Configuration

L'intégration se configure via l'interface graphique de Home Assistant. Deux choix sont proposés :

| Mode | Description |
|---|---|
| **Une équipe NBA** | Le prochain match et le calendrier complet de la saison d'une équipe |
| **La ligue NBA** | Les classements des deux conférences et les matchs de la semaine |

Ajoutez l'intégration plusieurs fois pour suivre plusieurs équipes (une seule entrée par équipe). Aucune date n'est à saisir : la saison en cours est déterminée automatiquement.

## Capteurs créés

Chaque entrée crée un appareil (l'équipe, ou « NBA ») regroupant ses capteurs.

### Mode Équipe
Exemple pour les Lakers :

| Capteur | Contenu |
|---|---|
| `sensor.nbalive_next_los_angeles_lakers` | Prochain match, match en cours ou match terminé depuis moins de 48 h |
| `sensor.nbalive_nba_team_los_angeles_lakers` | Calendrier complet de la saison (présaison, saison régulière, play-in, playoffs) |

La saison suivante est prise en compte à partir du 1er juillet.

### Mode Ligue

| Capteur | Contenu |
|---|---|
| `sensor.nbalive_classifica_nba_east` | Classement de la Conférence Est |
| `sensor.nbalive_classifica_nba_west` | Classement de la Conférence Ouest |
| `sensor.nbalive_all_nba` | Matchs de J-1 à J+4 ; hors saison, les 5 premiers jours de matchs à venir |

### Mise à jour depuis une version précédente

Les entrées existantes sont migrées automatiquement et gardent leurs `entity_id`. Les modes supprimés sont convertis :
- **Championnat** et **Tous les matchs du jour** deviennent le mode **Ligue** ;
- **Équipe NBA**, **ID d'équipe manuel** et **Équipe** (championnat `nba`) deviennent le mode **Équipe** ;
- le capteur `nbalive_all_mixed_*` est supprimé ;
- une équipe de football ne peut pas être convertie : supprimez l'entrée concernée.

## Attributs des capteurs

Chaque élément de la liste `matches` contient :

```yaml
date: "23/05/2026 20:30"
match_id: "401585390"
home_team: "Los Angeles Lakers"
home_logo: "https://..."
home_score: "112"
home_linescores: ["28", "30", "27", "27"]   # Score par quart-temps
home_overall: "52-30"                        # Bilan général
home_home: "28-13"                           # Bilan à domicile
home_road: "24-17"                           # Bilan à l'extérieur
home_leaders:
  points:
    player: "LeBron James"
    value: "28"
    headshot: "https://..."
  rebounds:
    player: "Anthony Davis"
    value: "14"
  assists:
    player: "LeBron James"
    value: "8"
home_statistics: { ... }
away_team: "Boston Celtics"
away_logo: "https://..."
away_score: "105"
away_linescores: ["25", "28", "26", "26"]
away_overall: "61-21"
away_home: "32-9"
away_road: "29-12"
away_leaders: { ... }
away_statistics: { ... }
state: "post"          # pre | in | post
status: "Final"
clock: "0:00"
period: 4
venue: "Crypto.com Arena"
match_details:
  - "Jump Ball - 0:00: LeBron James"
player_stats:          # Disponible uniquement après le match (state: post)
  home_players:
    team_name: "Los Angeles Lakers"
    players:
      - name: "LeBron James"
        position: "SF"
        jersey: "23"
        starter: true
        stats:
          minutes: "38"
          pts: "28"
          reb: "8"
          ast: "8"
          fg: "11-19"
          3pt: "2-6"
          ft: "4-4"
          stl: "1"
          blk: "0"
          to: "3"
          plusMinus: "+7"
  away_players: { ... }
```

## Exclure les capteurs de l'historique

Les attributs volumineux (`matches`, `standings`, `league_info`) ne sont déjà pas enregistrés dans l'historique. Pour exclure entièrement les capteurs, ajoutez dans `configuration.yaml` :

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.nbalive_*
```

## Exemples d'automatisations

### Notification 15 minutes avant un match

```yaml
alias: NBA Live - Notification 15 min avant le match des Lakers
triggers:
  - trigger: template
    value_template: >
      {{
        (as_timestamp(strptime(
          state_attr('sensor.nbalive_next_los_angeles_lakers', 'matches')[0].date,
          '%d/%m/%Y %H:%M'
        )) - 900) | timestamp_custom('%Y-%m-%d %H:%M') == now().strftime('%Y-%m-%d %H:%M')
      }}
conditions:
  - condition: template
    value_template: >
      {{ state_attr('sensor.nbalive_next_los_angeles_lakers', 'matches')[0].state == 'pre' }}
actions:
  - action: notify.mobile_app_xxx
    data:
      title: "NBA Live - Match dans 15 minutes !"
      message: >
        {{ state_attr('sensor.nbalive_next_los_angeles_lakers', 'matches')[0].home_team }}
        vs
        {{ state_attr('sensor.nbalive_next_los_angeles_lakers', 'matches')[0].away_team }}
mode: single
```

### Notification de score en temps réel

```yaml
alias: NBA Live - Score en direct des Lakers
triggers:
  - trigger: template
    value_template: >
      {% set m = state_attr('sensor.nbalive_next_los_angeles_lakers', 'matches') %}
      {% if m and m | length > 0 %}{{ m[0].state == 'in' }}{% endif %}
actions:
  - action: notify.mobile_app_xxx
    data:
      title: "NBA Live - Score en direct"
      message: >
        {% set m = state_attr('sensor.nbalive_next_los_angeles_lakers', 'matches')[0] %}
        {{ m.home_team }} {{ m.home_score }} - {{ m.away_score }} {{ m.away_team }}
        (Q{{ m.period }} - {{ m.clock }})
mode: single
```

## Notes

- Vous pouvez créer plusieurs instances de l'intégration pour suivre plusieurs équipes ou ligues simultanément.
- Le nom des capteurs utilise le préfixe `nbalive_`.
- Les statistiques détaillées des joueurs (`player_stats`) ne sont disponibles qu'après la fin du match (`state: post`).
