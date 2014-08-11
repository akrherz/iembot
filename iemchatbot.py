""" Chat bot implementation of IEMBot """

# http://stackoverflow.com/questions/7016602
from twisted.web.client import HTTPClientFactory
HTTPClientFactory.noisy = False
from twisted.mail.smtp import SMTPSenderFactory
SMTPSenderFactory.noisy = False

from twisted.words.protocols.jabber import jid
from twisted.words.xish import xpath
from twisted.python import log
from twisted.web import server, resource

from twisted.internet.task import LoopingCall
from twisted.internet import reactor


import PyRSS2Gen

import datetime
import re
import pickle
import os
import json

from lib import basicbot

CHATLOG = {}

# Increment this as we change the structure of the CHATLOG variable
PICKLEFILE = "iembot_chatlog_v1.pickle"
SEQNUM0 = 0
if os.path.isfile(PICKLEFILE):
    try:
        CHATLOG = pickle.load( open(PICKLEFILE, 'r') )
        for rm in CHATLOG.keys():
            s = CHATLOG[rm]['seqnum'][-1]
            if s is not None and int(s) > SEQNUM0:
                SEQNUM0 = int(s)
                #log.msg("Setting SEQNUM to %s" % (SEQNUM0,))
        log.msg("Loaded CHATLOG pickle: %s"  % (PICKLEFILE,))
    except Exception,exp:
        log.err(exp)

def saveChatLog():
    reactor.callInThread(really_save_chat_log)

def really_save_chat_log():
    """ Save the pickle file """
    log.msg('Saving CHATLOG to %s' % (PICKLEFILE,))
    pickle.dump( CHATLOG, open(PICKLEFILE,'w'))

lc2 = LoopingCall(saveChatLog)
lc2.start( 600 ) # Every 10 minutes

class JabberClient(basicbot.basicbot):
    """ I am a Jabber Bot
    
    I provide some customizations that are not provided by basicbot, here are
    some details on calling order
    
    1. Twisted .tac calls 'basicbot.fire_client_with_config'
    2. jabber.client callsback 'authd' when we login
       -> 'authd' will call on_firstlogin when this is the first_run
       -> 'auth' will call on_login
    3-inf. jabber.client callsback 'authd' when we get logged in 
       -> 'auth' will call on_login
    """

        
    def on_firstlogin(self):
        """ local stuff that we care about, that gets called on first login """
        
        # We use a sequence number on the messages to track things
        self.seqnum = SEQNUM0

    def processMessageGC(self, elem):
        ''' Process a stanza element that is from a chatroom '''
        # Ignore all messages that are x-stamp (delayed / room history)
        if xpath.queryForNodes("/message/x[@xmlns='jabber:x:delay']", elem):
            return

        _from = jid.JID( elem["from"] )
        room = _from.user
        res = _from.resource
        
        
        body = xpath.queryForString('/message/body', elem)
        if body is not None and len(body) >= 4 and body[:4] == "ping":
            self.send_groupchat(room, "%s: %s" % (res, self.get_fortune() ) )

        # In order for the message to be logged, it needs to be from iembot
        # and have a channels attribute
        if res is None or res != 'iembot':
            return
        
        a = xpath.queryForNodes("/message/x[@xmlns='nwschat:nwsbot']", elem)
        if a is None or len(a) == 0:
            return
        
        if not CHATLOG.has_key(room):
            CHATLOG[room] = {'seqnum': [-1]*40, 'timestamps': [0]*40, 
                             'log': ['']*40, 'author': ['']*40,
                             'product_id': ['']*40, 'txtlog': ['']*40}
        ts = datetime.datetime.utcnow()
        x = xpath.queryForNodes("/message/x[@xmlns='jabber:x:delay']", elem)
        if x is not None and x[0].hasAttribute("stamp"):
            xdelay = x[0]['stamp']
            ts = datetime.datetime.strptime(xdelay, "%Y%m%dT%H:%M:%S")
            
        product_id = ''
        if elem.x and elem.x.hasAttribute("product_id"):
            product_id = elem.x['product_id']

        html = xpath.queryForNodes('/message/html/body', elem)
        logEntry = body
        if html is not None:
            logEntry = html[0].toXml()

            
        CHATLOG[room]['seqnum'] = CHATLOG[room]['seqnum'][1:] + [self.next_seqnum(),]
        CHATLOG[room]['timestamps'] = CHATLOG[room]['timestamps'][1:] + [ts.strftime("%Y%m%d%H%M%S"),]
        CHATLOG[room]['author'] = CHATLOG[room]['author'][1:] + [res,]
        CHATLOG[room]['product_id'] = CHATLOG[room]['product_id'][1:] + [product_id,]
        CHATLOG[room]['log'] = CHATLOG[room]['log'][1:] + [logEntry,]
        CHATLOG[room]['txtlog'] = CHATLOG[room]['txtlog'][1:] + [body,]
        
    def processMessagePC(self, elem):
        #log.msg("processMessagePC() called from %s...." % (elem['from'],))
        _from = jid.JID( elem["from"] )
        if (elem["from"] == self.config['bot.xmppdomain']):
            log.msg("MESSAGE FROM SERVER?")
            return
        # Intercept private messages via a chatroom, can't do that :)
        if _from.host == self.config['bot.mucservice']:
            log.msg("ERROR: message is MUC private chat")
            return

        if _from.userhost() != "iembot_ingest@%s" % (
                                            self.config['bot.xmppdomain']):
            log.msg("ERROR: message not from iembot_ingest")
            return

        # Go look for body to see routing info! 
        # Get the body string
        bstring = xpath.queryForString('/message/body', elem)
        if not bstring:
            log.msg("Nothing found in body?")
            return
        
        if elem.x and elem.x.hasAttribute("channels"):
            channels = elem.x['channels'].split(",")
        else:
            # The body string contains
            channel = bstring.split(":", 1)[0]
            channels = [channel,]
            # Send to chatroom, clip body of channel notation
            #elem.body.children[0] = meat

        # Always send to botstalk
        elem['to'] = "botstalk@%s" % (self.config['bot.mucservice'],)
        elem['type'] = "groupchat"
        self.xmlstream.send( elem )

        for channel in channels:
            for room in self.routingtable.get(channel, []):
                elem['to'] = "%s@%s" % (room, 
                                            self.config['bot.mucservice'])
                self.xmlstream.send( elem )
            for page in self.tw_routingtable.get(channel, []):
                if not self.tw_access_tokens.has_key(page):
                    log.msg("Failed to tweet due to no access_tokens for %s" % (
                                                page,))
                    continue
                # Require the x.twitter attribute to be set to prevent 
                # confusion with some ingestors still sending tweets themself
                if not elem.x.hasAttribute("twitter"):
                    #log.msg("skip message due to no twitter attr")
                    continue
                twtextra = {}
                if (elem.x and elem.x.hasAttribute("lat") and 
                    elem.x.hasAttribute("long")):
                    twtextra['lat'] = elem.x['lat']
                    twtextra['long'] = elem.x['long']
                log.msg("Sending tweet %s" % (elem.x['twitter'],))
                # Finally, actually tweet, this is in basicbot
                self.tweet(elem.x['twitter'], self.tw_access_tokens[page],
                           twtextra=twtextra, twituser=page)

    def tweet_eb(self, err, twttxt, room, myjid, twituser):
        ''' twitter update errorback '''
        log.msg('tweet_eb: [%s] on %s' % (twituser, twttxt))
        log.err( err )

    def tweet_cb(self, res, twttxt, room, myjid, twituser):
        ''' twitter callback '''
        log.msg('tweet_cb: [%s] Res: %s' % (twituser, res))
        url = "https://twitter.com/%s/status/%s" % (twituser, res)
        
        self.send_groupchat("twitter", "%s %s" % (twttxt, url))


xml_cache = {}
xml_cache_expires = {}


def wfoRSS(rm):
    if len(rm) == 4 and rm[0] == 'k':
        rm = '%schat' % (rm[-3:],)
    elif len(rm) == 3:
        rm = 'k%schat' % (rm,)
    if not xml_cache.has_key(rm):
        xml_cache[rm] = ""
        xml_cache_expires[rm] = -2

    lastID = CHATLOG[rm]['seqnum'][-1]
    if lastID == xml_cache_expires[rm]:
        #log.msg('Using cached RSS for room: %s' % (rm,))
        return xml_cache[rm]

    rss = PyRSS2Gen.RSS2(
           generator = "iembot",
           title = "IEMBOT Feed",
           link = "http://weather.im/iembot-rss/wfo/"+ rm +".xml",
           description = "IEMBOT RSS Feed of %s" % (rm,),
           lastBuildDate = datetime.datetime.utcnow() )

    for k in range(len(CHATLOG[rm]['seqnum'])-1,0,-1 ):
        if CHATLOG[rm]['seqnum'][k] < 0:
            continue
        ts = datetime.datetime.strptime( CHATLOG[rm]['timestamps'][k],
                                         "%Y%m%d%H%M%S")
        txt = CHATLOG[rm]['txtlog'][k]
        urlpos = txt.find("http://")
        if (urlpos == -1):
            txt += "  "
        ltxt = txt[urlpos:].replace("&amp;","&").strip()
        if (ltxt == ""):
            ltxt = "http://mesonet.agron.iastate.edu/projects/iembot/"
        rss.items.append( 
          PyRSS2Gen.RSSItem(
            title = txt[:urlpos],
            link =  ltxt, guid = ltxt, 
            pubDate = ts.strftime("%a, %d %b %Y %H:%M:%S") ) )

    xml_cache[rm] = rss.to_xml()
    xml_cache_expires[rm] = lastID
    return rss.to_xml()

class HomePage(resource.Resource):

    def isLeaf(self):
        return True
    def __init__(self):
        resource.Resource.__init__(self)

    def render(self, request):
        #html = "<html><h4>"+ `dir(self.server)` + request.uri +"</h4></html>"
        tokens = re.findall("/wfo/(k...|botstalk).xml",request.uri.lower())
        if len(tokens) == 0:
            return "ERROR!"
        
        rm = tokens[0]
        if len(rm) == 4 and rm[0] == 'k':
            rm = '%schat' % (rm[-3:],)
        elif len(rm) == 3:
            rm = 'k%schat' % (rm,)
        #log.msg("Looking for CHATLOG room: %s" % (rm,))
        if not CHATLOG.has_key(rm):
            rss = PyRSS2Gen.RSS2(
            generator = "iembot",
            title = "IEMBOT Feed",
            link = "http://weather.im/iembot-rss/wfo/"+ tokens[0] +".xml",
            description = "Syndication of iembot messages.",
            lastBuildDate = datetime.datetime.utcnow() )
            rss.items.append( 
              PyRSS2Gen.RSSItem(
               title = "IEMBOT recently restarted, no history yet",
               link =  "http://mesonet.agron.iastate.edu/projects/iembot/",
               pubDate =  datetime.datetime.utcnow() ) )
            xml = rss.to_xml()
        else:
            xml = wfoRSS(rm )
        request.setHeader('Content-Length', "%s" % (len(xml),))
        request.setHeader('Content-Type', 'text/xml')
        request.setResponseCode(200)
        request.write( xml )
        request.finish()
        return server.NOT_DONE_YET


class RootResource(resource.Resource):
    def __init__(self):
        resource.Resource.__init__(self)
        self.putChild('wfo', HomePage())

class JsonChannel(resource.Resource):

    def isLeaf(self):
        return True


    def wrap(self, request, j):
        """ Support specification of a JSONP callback """
        if request.args.has_key('callback'):
            request.setHeader("Content-type", "application/javascript")
            return '%s(%s);' % (request.args['callback'][0], j)
        else:
            return j

    def render(self, request):
        """ Process the request that we got, it should look something like:
        /room/dmxchat?seqnum=1
        """
        tokens = re.findall("/room/([a-z0-9]+)",request.uri.lower())
        if len(tokens) == 0:
            log.msg('Bad URI: %s len(tokens) is 0' % (request.uri,))
            request.write( self.wrap(request, json.dumps("ERROR")) )
            request.finish()
            return server.NOT_DONE_YET
        
        room = tokens[0]
        seqnum = request.args.get('seqnum')
        if seqnum is None or len(seqnum) != 1:
            log.msg('Bad URI: %s seqnum problem' % (request.uri,))
            request.write( self.wrap(request, json.dumps("ERROR")) )
            request.finish()
            return server.NOT_DONE_YET
        seqnum = int(seqnum[0])

        r = {'messages': [],}
        if not CHATLOG.has_key(room):
            print 'No CHATLOG', room
            request.write( self.wrap(request, json.dumps("ERROR")) )
            request.finish()
            return server.NOT_DONE_YET
        #print 'ROOM: %s RESEQ: %s SEQ0: %s SEQ-1: %s' % (room,
        #        seqnum, CHATLOG[room]['seqnum'][0], CHATLOG[room]['seqnum'][-1])
        for k in range(len(CHATLOG[room]['seqnum'])):
            if (CHATLOG[room]['seqnum'][k] > seqnum):
                ts = datetime.datetime.strptime(CHATLOG[room]['timestamps'][k],
                                                "%Y%m%d%H%M%S")
                r['messages'].append({'seqnum': CHATLOG[room]['seqnum'][k], 
                                     'ts': ts.strftime("%Y-%m-%d %H:%M:%S"), 
                                     'author': CHATLOG[room]['author'][k], 
                                     'product_id': CHATLOG[room]['product_id'][k],
                                     'message': CHATLOG[room]['log'][k] } )

        request.write( self.wrap(request, json.dumps(r)) )
        request.finish()
        return server.NOT_DONE_YET

class AdminChannel(resource.Resource):

    def isLeaf(self):
        return True
    
    def __init__(self, iembot):
        resource.Resource.__init__(self)
        self.iembot = iembot
        
    def render(self, request):
        log.msg("Reloading iembot room configuration....")
        self.iembot.load_chatrooms(False)
        self.iembot.load_twitter()
        request.write( json.dumps({}) )
        request.finish()
        return server.NOT_DONE_YET

class JSONResource(resource.Resource):
    def __init__(self, iembot):
        resource.Resource.__init__(self)
        self.putChild('room', JsonChannel())
        self.putChild('reload', AdminChannel(iembot))