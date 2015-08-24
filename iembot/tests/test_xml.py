import unittest
from iembot.basicbot import basicbot
from iembot.basicbot import safe_twitter_text


class TestXML(unittest.TestCase):

    def test_twittertext(self):
        """Tricky stuff when URLs are included"""
        msg = ("Tropical Storm #Danny Intermediate ADVISORY 23A issued. "
               "Outer rainbands spreading across the southern leeward "
               "islands. http://go.usa.gov/W3H")
        msg2 = safe_twitter_text(msg)
        self.assertEquals(msg2,
                          ('Tropical Storm #Danny Intermediate ADVISORY 23A '
                           'issued. Outer rainbands spreading across the '
                           'southern leeward... http://go.usa.gov/W3H'))

    def test_xml(self):
        bot = basicbot('testbot', None)
        msg = bot.send_groupchat('roomname', 'Hello Friend')
        self.assertTrue(msg is not None)

        msg = bot.send_groupchat('roomname', 'Hello Friend &')
        self.assertTrue(msg is not None)

        msg = bot.send_groupchat('roomname', 'Hello Friend &&amp;')
        self.assertTrue(msg is not None)
