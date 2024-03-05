"""Some random tests"""

from iembot.basicbot import basicbot
from iembot.util import safe_twitter_text


def test_twittertext():
    """Tricky stuff when URLs are included"""
    msg = (
        "Tropical Storm #Danny Intermediate ADVISORY 23A issued. "
        "Outer rainbands spreading across the southern leeward "
        "islands. http://go.usa.gov/W3H"
    )
    msg2 = safe_twitter_text(msg)
    assert msg2 == (
        "Tropical Storm #Danny Intermediate ADVISORY 23A "
        "issued. Outer rainbands spreading across the "
        "southern leeward islands. http://go.usa.gov/W3H"
    )


def test_xml():
    bot = basicbot("testbot", None, xml_log_path="/tmp")
    msg = bot.send_groupchat("roomname", "Hello Friend")
    assert msg is not None

    msg = bot.send_groupchat("roomname", "Hello Friend &")
    assert msg is not None

    msg = bot.send_groupchat("roomname", "Hello Friend &&amp;")
    assert msg is not None
