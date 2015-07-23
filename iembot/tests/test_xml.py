import unittest
from iembot.basicbot import basicbot


class TestXML(unittest.TestCase):

    def test_xml(self):
        bot = basicbot('testbot', None)
        bot.send_groupchat('roomname', 'Hello Friend')
        self.assertEquals(bot.name, 'testbot')
