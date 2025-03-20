"""Test things done with channel subs."""

import pytest

from iembot.basicbot import BasicBot
from iembot.util import (
    channels_room_add,
    channels_room_del,
    channels_room_list,
)


@pytest.mark.parametrize("database", ["mesosite"])
def test_room_list(bot: BasicBot, dbcursor):
    """Test listing of channel subscriptions for the room."""

    def _local(room, _msg):
        """Interception."""
        assert room == "test"

    channels_room_add(dbcursor, bot, "test", "XXX")

    bot.send_groupchat = _local
    channels_room_list(bot, "test")

    channels_room_del(dbcursor, bot, "test", "XXX")
