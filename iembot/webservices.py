"""Our web services"""
import json
import re
import datetime

from twisted.web import resource
from twisted.python import log
from feedgen.feed import FeedGenerator
import iembot.util as botutil

XML_CACHE = {}
XML_CACHE_EXPIRES = {}


def wfo_rss(iembot, rm):
    """build a RSS for the given room"""
    if len(rm) == 4 and rm[0] == 'k':
        rm = '%schat' % (rm[-3:],)
    elif len(rm) == 3:
        rm = 'k%schat' % (rm,)
    if rm not in XML_CACHE:
        XML_CACHE[rm] = ""
        XML_CACHE_EXPIRES[rm] = -2

    # should not be empty given the caller
    lastID = iembot.chatlog[rm][0].seqnum
    if lastID == XML_CACHE_EXPIRES[rm]:
        return XML_CACHE[rm]

    rss = FeedGenerator()
    rss.generator('iembot')
    rss.title("%s IEMBot RSS Feed" % (rm,))
    rss.link(href="https://weather.im/iembot-rss/wfo/%s.xml" % (rm,),
             rel='self')
    rss.description("%s IEMBot RSS Feed" % (rm,))
    rss.lastBuildDate(
        datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT"))

    for entry in iembot.chatlog[rm]:
        botutil.add_entry_to_rss(entry, rss)

    XML_CACHE[rm] = rss.rss_str()
    XML_CACHE_EXPIRES[rm] = lastID
    return rss.rss_str()


class RSSService(resource.Resource):
    """Our RSS service"""

    def isLeaf(self):
        """allow uri"""
        return True

    def __init__(self, iembot):
        """Constructor"""
        resource.Resource.__init__(self)
        self.iembot = iembot

    def render(self, request):
        uri = request.uri.decode('utf-8')
        if uri.startswith("/wfo/"):
            tokens = re.findall("/wfo/(k...|botstalk).xml", uri.lower())
        else:
            tokens = re.findall("/room/(.*).xml", uri.lower())
        if not tokens:
            return b"ERROR!"

        rm = tokens[0]
        if uri.startswith("/wfo/"):
            if len(rm) == 4 and rm[0] == 'k':
                rm = '%schat' % (rm[-3:],)
            elif len(rm) == 3:
                rm = 'k%schat' % (rm,)
        if not self.iembot.chatlog.get(rm, []):
            rss = FeedGenerator()
            rss.generator('iembot')
            rss.title("IEMBot RSS Feed")
            rss.link(
                href="https://weather.im/iembot-rss/wfo/%s.xml" % (tokens[0],),
                rel='self')
            rss.description("Syndication of iembot messages.")
            rss.lastBuildDate(datetime.datetime.utcnow())
            fe = rss.add_entry()
            fe.title("IEMBOT recently restarted, no history yet")
            fe.link(href="http://mesonet.agron.iastate.edu/projects/iembot/",
                    rel='self')
            fe.pubDate(datetime.datetime.utcnow(
                ).strftime("%a, %d %b %Y %H:%M:%S GMT"))
            xml = rss.rss_str()
        else:
            xml = wfo_rss(self.iembot, rm)
        request.setHeader('Content-Length', "%s" % (len(xml),))
        request.setHeader('Content-Type', 'text/xml')
        request.setResponseCode(200)
        return xml


class RSSRootResource(resource.Resource):
    """I answer iembot-rss requests"""

    def __init__(self, iembot):
        """Constructor"""
        resource.Resource.__init__(self)
        service = RSSService(iembot)
        # legacy and lame
        self.putChild(b'wfo', service)
        # more properly alligned with what we do
        self.putChild(b'room', service)


# ------------------- iembot-json stuff below ---------------
class RoomChannel(resource.Resource):
    """respond to room requests"""

    def isLeaf(self):
        """allow uri calling"""
        return True

    def __init__(self, iembot):
        """Constructor"""
        resource.Resource.__init__(self)
        self.iembot = iembot

    def wrap(self, request, j):
        """ Support specification of a JSONP callback """
        if 'callback' in request.args:
            request.setHeader("Content-type", "application/javascript")
            return ('%s(%s);' % (request.args['callback'][0], j)
                    ).encode('utf-8')
        return j.encode('utf-8')

    def render(self, request):
        """ Process the request that we got, it should look something like:
        /room/dmxchat?seqnum=1
        """
        uri = request.uri.decode('utf-8')
        tokens = re.findall("/room/([a-z0-9]+)", uri.lower())
        if not tokens:
            log.msg('Bad URI: %s len(tokens) is 0' % (uri, ))
            return self.wrap(request, json.dumps("ERROR"))

        room = tokens[0]
        seqnum = request.args.get(b'seqnum')
        if seqnum is None or len(seqnum) != 1:
            log.msg('Bad URI: %s seqnum problem' % (request.uri,))
            return self.wrap(request, json.dumps("ERROR"))
        seqnum = int(seqnum[0])

        r = dict(messages=[])
        if room not in self.iembot.chatlog:
            print('No CHATLOG |%s|' % (room, ))
            return self.wrap(request, json.dumps("ERROR"))
        for entry in self.iembot.chatlog[room][::-1]:
            if entry.seqnum <= seqnum:
                continue
            ts = datetime.datetime.strptime(entry.timestamp, "%Y%m%d%H%M%S")
            r['messages'].append(
                {'seqnum': entry.seqnum,
                 'ts': ts.strftime("%Y-%m-%d %H:%M:%S"),
                 'author': entry.author,
                 'product_id': entry.product_id,
                 'message': entry.log})

        return self.wrap(request, json.dumps(r))


class ReloadChannel(resource.Resource):
    """respond to /reload requests"""

    def isLeaf(self):
        """allow URI calling"""
        return True

    def __init__(self, iembot):
        """Constructor"""
        resource.Resource.__init__(self)
        self.iembot = iembot

    def render(self, request):
        log.msg("Reloading iembot room configuration....")
        self.iembot.load_chatrooms(False)
        self.iembot.load_twitter()
        return json.dumps("OK").encode('utf-8')


class JSONRootResource(resource.Resource):
    """answer /iembot-json/ requests"""

    def __init__(self, iembot):
        """Constructor"""
        resource.Resource.__init__(self)
        self.putChild(b'room', RoomChannel(iembot))
        self.putChild(b'reload', ReloadChannel(iembot))
