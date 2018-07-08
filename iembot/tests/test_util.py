"""Tests, gasp"""
import iembot.util as botutil


def test_tweettext():
    """Are we doing the right thing here"""
    msgin = ("At 1:30 PM, 1 WNW Lake Mills [Winnebago Co, IA] TRAINED "
             "SPOTTER reports TSTM WND GST of E61 MPH. SPOTTER MEASURED "
             "61 MPH WIND GUST. HIS CAR DOOR WAS ALSO CAUGHT BY THE WIND "
             "WHEN HE WAS OPENING THE DOOR, PUSHING THE DOOR INTO HIS FACE. "
             "THIS CONTACT BR.... "
             "https://iem.local/lsr/#DMX/201807041830/201807041830")
    msgout = botutil.safe_twitter_text(msgin)
    assert msgout == msgin
