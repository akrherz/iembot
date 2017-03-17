"""Utility functions for IEMBot"""
import PyRSS2Gen
import datetime
import re

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
    