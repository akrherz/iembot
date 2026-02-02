"""Some random tests"""


def test_xml(bot):
    msg = bot.send_groupchat("roomname", "Hello Friend")
    assert msg is not None

    msg = bot.send_groupchat("roomname", "Hello Friend &")
    assert msg is not None

    msg = bot.send_groupchat("roomname", "Hello Friend &&amp;")
    assert msg is not None
