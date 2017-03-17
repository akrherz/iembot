import unittest
import iembot.util as botutil

class TestCase(unittest.TestCase):

    def test_chatlog2rssitem(self):
        """Can we do it, yes we can!"""
        uri = "https://mesonet.agron.iastate.edu/p.php?pid=201703171339-KLWX-FXUS61-AFDLWX"
        rssitem = botutil.chatlog2rssitem('201703171339',
                                          ("LWX issues Area Forecast Discussion (AFD) %s"
                                           ) % (uri,))
        self.assertEquals(rssitem.title, "LWX issues Area Forecast Discussion (AFD)")
        self.assertEquals(rssitem.link, uri)
        self.assertEquals(rssitem.guid, uri)
