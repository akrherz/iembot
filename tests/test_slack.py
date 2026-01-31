"""Exercises Slack related tests."""

from unittest import mock

from iembot import slack


def test_send_to_slack(monkeypatch):
    """Test sending to Slack."""
    posted = {}

    def mock_post(url, headers, data):
        """Mock requests.post"""
        posted["url"] = url
        posted["headers"] = headers
        posted["data"] = data

        class MockResponse:
            """Mock response object."""

            def __init__(self):
                self.content = b'{"ok":true}'

            def raise_for_status(self):
                """Mock raise for status."""

        return MockResponse()

    monkeypatch.setattr(slack.requests, "post", mock_post)

    bot = mock.Mock()
    bot.slack_teams = {"T12345": "xoxb-fake-token"}
    team_id = "T12345"
    channel_id = "C67890"
    elem = mock.Mock()
    elem.x = {"twitter": "Hello, Slack!"}

    slack.send_to_slack(bot, team_id, channel_id, elem)

    assert posted["url"] == "https://slack.com/api/chat.postMessage"
    assert posted["headers"]["Authorization"] == "Bearer xoxb-fake-token"
    assert posted["headers"]["Content-Type"] == "application/json"
    import json as jsonlib

    data = jsonlib.loads(posted["data"])
    assert data["text"] == "Hello, Slack!"
    assert data["channel"] == channel_id
    assert data["mrkdwn"] is False


def test_install(bot):
    """Test the status renderer."""
    ss = slack.SlackInstallChannel(bot)
    request = mock.Mock()
    request.setResponseCode = mock.Mock()
    request.write = mock.Mock()
    assert ss.render(request) is not None
