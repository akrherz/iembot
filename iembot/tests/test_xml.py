import unittest
from iembot.basicbot import basicbot


class TestXML(unittest.TestCase):

    def test_xml(self):
        bot = basicbot('testbot', None)
        msg = bot.send_groupchat('roomname', 'Hello Friend')
        self.assertTrue(msg is not None)

        msg = bot.send_groupchat('roomname', 'Hello Friend &')
        self.assertTrue(msg is not None)

        msg = bot.send_groupchat('roomname', 'Hello Friend &&amp;')
        self.assertTrue(msg is not None)
