"""Utility functions for IEMBot"""
import datetime
import re

import PyRSS2Gen
from pyiem.reference import TWEET_CHARS


def safe_twitter_text(text):
    """ Attempt to rip apart a message that is too long!
    To be safe, the URL is counted as 24 chars
    """
    # Convert two or more spaces into one
    text = ' '.join(text.split())
    # If we are already below TWEET_CHARS, we don't have any more work to do...
    if len(text) < TWEET_CHARS and text.find("http") == -1:
        return text
    chars = 0
    words = text.split()
    # URLs only count as 25 chars, so implement better accounting
    for word in words:
        if word.startswith('http'):
            chars += 25
        else:
            chars += (len(word) + 1)
    if chars < TWEET_CHARS:
        return text
    urls = re.findall('https?://[^\s]+', text)
    if len(urls) == 1:
        text2 = text.replace(urls[0], '')
        sections = re.findall('(.*) for (.*)( till [0-9A-Z].*)', text2)
        if len(sections) == 1:
            text = "%s%s%s" % (sections[0][0], sections[0][2], urls[0])
            if len(text) > TWEET_CHARS:
                sz = TWEET_CHARS - 26 - len(sections[0][2])
                text = "%s%s%s" % (sections[0][0][:sz], sections[0][2],
                                   urls[0])
            return text
        if len(text) > TWEET_CHARS:
            # 25 for URL, three dots and space for 29
            return "%s... %s" % (text2[:(TWEET_CHARS - 29)], urls[0])
    if chars > TWEET_CHARS:
        if words[-1].startswith('http'):
            i = -2
            while len(' '.join(words[:i])) > (TWEET_CHARS - 3 - 25):
                i -= 1
            return ' '.join(words[:i]) + '... ' + words[-1]
    return text[:TWEET_CHARS]


def chatlog2rssitem(timestamp, txt):
    """Convert a txt Jabber room message to a RSS feed entry

    Args:
      timestamp(str): A string formatted timestamp in the form YYYYMMDDHHMI
      txt(str): The text variant of the chatroom message that was set.

    Returns:
      PyRSSGen.RSSItem
    """
    ts = datetime.datetime.strptime(timestamp, "%Y%m%d%H%M%S")
    m = re.search(r"https?://", txt)
    urlpos = -1
    if m:
        urlpos = m.start()
    else:
        txt += "  "
    ltxt = txt[urlpos:].replace("&amp;", "&").strip()
    if ltxt == "":
        ltxt = "https://mesonet.agron.iastate.edu/projects/iembot/"
    return PyRSS2Gen.RSSItem(title=txt[:urlpos].strip(),
                             link=ltxt,
                             guid=ltxt,
                             pubDate=ts.strftime("%a, %d %b %Y %H:%M:%S GMT"))
    