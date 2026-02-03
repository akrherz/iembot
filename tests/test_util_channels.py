"""Test things done with channel subs."""

import pytest

from iembot.bot import JabberClient
from iembot.util import (
    channels_room_add,
    channels_room_del,
    channels_room_list,
)


@pytest.mark.parametrize("database", ["iembot"])
def test_room_list(bot: JabberClient, dbcursor):
    """Test listing of channel subscriptions for the room."""

    def _local(room, _msg):
        """Interception."""
        assert room == "dmxchat"

    channels_room_add(dbcursor, bot, "dmxchat", "XXX")

    bot.send_groupchat = _local
    channels_room_list(bot, "dmxchat")

    channels_room_del(dbcursor, bot, "dmxchat", "XXX")
