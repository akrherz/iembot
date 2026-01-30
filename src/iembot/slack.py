"""Slack integration work."""

import json

import requests
from twisted.python import log
from twisted.words.xish.domish import Element


def send_to_slack(bot, team_id: str, channel_id: str, elem: Element):
    """Send a message to Slack, called from thread."""
    access_token = bot.slack_teams[team_id]
    payload = {
        "text": elem.x["twitter"],
        "mrkdwn": False,
        "channel": channel_id,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    log.msg("Posting to slack")
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=headers,
        data=json.dumps(payload),
    )
    log.msg(f"Got response {resp} {resp.content}")
    resp.raise_for_status()


def load_slack_from_db(txn, bot):
    """Load the Slack integration."""
    txn.execute(
        """
    select t.team_id, s.channel_id, s.subkey, t.access_token from
    iembot_slack_teams t JOIN iembot_slack_subscriptions s
    on (t.team_id = s.team_id)
        """
    )
    teams = {}
    rt = {}
    for row in txn.fetchall():
        # meh, redundant
        teams[row["team_id"]] = row["access_token"]
        d = rt.setdefault(row["subkey"], [])
        # sigh
        d.append(f"{row['team_id']}|{row['channel_id']}")

    bot.slack_teams = teams
    bot.slack_routingtable = rt
    log.msg(f"Loaded {len(teams)} Slack teams")
    log.msg(f"Loaded {len(rt)} Slack subscriptions")
