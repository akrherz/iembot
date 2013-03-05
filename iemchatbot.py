# Copyright (c) 2005 Iowa State University
# http://mesonet.agron.iastate.edu/ -- mailto:akrherz@iastate.edu
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
""" Chat bot implementation of IEMBot """

from twisted.words.protocols.jabber import jid
from twisted.words.xish import domish, xpath
from twisted.python import log
from twisted.web import server, resource
from twisted.enterprise import adbapi
from twisted.words.xish.xmlstream import STREAM_END_EVENT
from twisted.internet.task import LoopingCall
from twisted.internet import reactor
import PyRSS2Gen

import datetime
import re
import pickle
import os
import json

import ConfigParser
config = ConfigParser.ConfigParser()
config.read('config.ini')


DBPOOL = adbapi.ConnectionPool("twistedpg", 
                               database=config.get('database','name'), 
                               cp_reconnect=True,
                               host=config.get('database','host'))


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

ROUTES = {
  'MSR': ['ncrfcchat', 'ncrfcagencieschat'],
  'ORN': ['lmrfcchat'],
  'ALR': ['serfcchat'],
  'RHA': ['marfcchat'],
  'TIR': ['ohrfcchat'],
  'FWR': ['wgrfcchat'],
  'KRF': ['mbrfcchat'],
  'PTR': ['mwrfcchat'],
  'RSA': ['cnrfcchat'],
  'STR': ['cbrfcchat'],
  'TAR': ['nerfcchat'],
  'TUA': ['abrfcchat'],
  'ACR': ['aprfcchat'],
}

class JabberClient:

    def __init__(self, myjid, appriss):
        """ Constructor """
        self.xmlstream = None
        self.myjid = myjid
        self.seqnum = SEQNUM0
        self.appriss = appriss
        self.rooms = []
        self.routingtable = {}

    def send_presence(self):
        """ Send presence """
        presence = domish.Element(('jabber:client','presence'))
        presence.addElement('status').addContent('At your service...')
        self.xmlstream.send(presence)


    def keepalive(self):
        """ Whitespace ping for now... Openfire < 3.6.0 does not 
            support XMPP-Ping
        """
        if self.xmlstream is not None:
            self.xmlstream.send(' ')

    def rawDataInFn(self, data):
        if data == ' ':
            return
        log.msg("IEMBOT_RECV %s" % (data,))
        
    def rawDataOutFn(self, data):
        if data == ' ':
            return
        log.msg("IEMBOT_SEND %s" % (data,))
        
    def authd(self, xmlstream):
        log.msg("Logged into local jabber server")
        self.rooms = []
        self.xmlstream = xmlstream
        self.xmlstream.rawDataInFn = self.rawDataInFn
        self.xmlstream.rawDataOutFn = self.rawDataOutFn

        self.xmlstream.addObserver('/message',  self.processor)

        self.send_presence()
        self.join_chatrooms()
        lc = LoopingCall(self.keepalive)
        lc.start(60)
        self.xmlstream.addObserver(STREAM_END_EVENT, lambda _: lc.stop())

    def compute_daily_caller(self):
        # Figure out when to spam all rooms with a timestamp
        utc = datetime.datetime.utcnow() + datetime.timedelta(days=1)
        tnext =  utc.replace(hour=0,minute=0,second=0)
        log.msg('Initial Calling daily_timestamp in %s seconds' % (
                            (tnext - datetime.datetime.utcnow()).seconds, ))
        reactor.callLater((tnext - datetime.datetime.utcnow()).seconds, 
                          self.daily_timestamp)

    def join_chatrooms(self):
        df = DBPOOL.runInteraction(self.load_chatrooms)
        df.addErrback( log.err )
        
    def load_chatrooms(self, txn):
        
        txn.execute("""SELECT roomname from iembot_rooms""")
        cnt = 0
        for row in txn:
            rm = row['roomname']
            if rm in self.rooms:
                continue
            self.rooms.append( rm )
            presence = domish.Element(('jabber:client','presence'))
            presence['to'] = "%s@conference.%s/iembot" % (rm, 
                                        config.get('local','xmppdomain') )
            reactor.callLater(cnt % 20, self.xmlstream.send, presence)
            cnt += 1
        log.msg("Attempted to join %s rooms" % (cnt,))

        txn.execute("""SELECT roomname, channel from iembot_room_subscriptions""")
        cnt = 0
        self.routingtable = {}
        for row in txn:
            rm = row['roomname']
            channel = row['channel']
            if not self.routingtable.has_key(channel):
                self.routingtable[channel] = []
            self.routingtable[channel].append( rm )
        log.msg("Loaded room subscriptions")


    def daily_timestamp(self):
        """  Send the timestamp into each room, each GMT day... """
        ts = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        mess = "------ %s [UTC] ------" % (ts.strftime("%b %d, %Y"),)
        for rm in self.rooms:
            self.send_groupchat(rm, mess)

        ts = ts + datetime.timedelta(days=1)
        tnext = ts.replace(hour=0,minute=0,second=0)
        log.msg('Calling daily_timestamp in %s seconds' % (
                                (tnext - datetime.datetime.utcnow()).seconds,))
        reactor.callLater( (tnext - datetime.datetime.utcnow()).seconds, 
                           self.daily_timestamp)

    def debug(self, elem):
        log.msg("IEMBOT_DEBUG %s" % (elem,))

    def nextSeqnum(self,):
        self.seqnum += 1
        return self.seqnum

    def processMessageGC(self, elem):
        _from = jid.JID( elem["from"] )
        room = _from.user
        res = _from.resource
        if res is None or res != 'iembot':
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
        body = xpath.queryForString('/message/body', elem)
        logEntry = body
        if html is not None:
            logEntry = html[0].toXml()

            
        CHATLOG[room]['seqnum'] = CHATLOG[room]['seqnum'][1:] + [self.nextSeqnum(),]
        CHATLOG[room]['timestamps'] = CHATLOG[room]['timestamps'][1:] + [ts.strftime("%Y%m%d%H%M%S"),]
        CHATLOG[room]['author'] = CHATLOG[room]['author'][1:] + [res,]
        CHATLOG[room]['product_id'] = CHATLOG[room]['product_id'][1:] + [product_id,]
        CHATLOG[room]['log'] = CHATLOG[room]['log'][1:] + [logEntry,]
        CHATLOG[room]['txtlog'] = CHATLOG[room]['txtlog'][1:] + [body,]


    def processor(self, elem):
        try:
            self.processMessage(elem)
        except Exception, exp:
            log.err( exp )

    def processMessage(self, elem):

        if not elem.hasAttribute("type") or elem['type'] not in ['chat',
                                                                 'groupchat']:
            return

        bstring = xpath.queryForString('/message/body', elem)
        if bstring == "":
            return

        if elem['type'] == "groupchat":
            self.processMessageGC(elem)
        if elem['type'] == "chat":
            self.processMessagePC(elem)
        

    def send_groupchat(self, room, mess, html=None):
        """ Send a groupchat message to the desired room """
        message = domish.Element(('jabber:client','message'))
        message['to'] = "%s@conference.%s" % (room, 
                                              config.get('local','xmppdomain'))
        message['type'] = "groupchat"
        message.addElement('body', None, mess)
        if html is not None:
            message.addRawXml("<html xmlns='http://jabber.org/protocol/xhtml-im'><body xmlns='http://www.w3.org/1999/xhtml'>"+ html +"</body></html>")
        self.xmlstream.send(message)


    def processMessagePC(self, elem):
        #log.msg("processMessagePC() called from %s...." % (elem['from'],))
        _from = jid.JID( elem["from"] )
        if (elem["from"] == config.get('local','xmppdomain')):
            log.msg("MESSAGE FROM SERVER?")
            return
        # Intercept private messages via a chatroom, can't do that :)
        if _from.host == "conference.%s" % (config.get('local','xmppdomain'),):
            log.msg("ERROR: message is MUC private chat")
            return

        if _from.userhost() != "iembot_ingest@%s" % (
                                            config.get('local','xmppdomain')):
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

        # Send to the APPRISS instance
        self.appriss.from_iembot( elem )

        # Always send to botstalk
        elem['to'] = "botstalk@conference.%s" % (config.get('local','xmppdomain'),)
        elem['type'] = "groupchat"
        self.xmlstream.send( elem )

        for channel in channels:
            for room in self.routingtable.get(channel, []):
                elem['to'] = "%s@conference.%s" % (room, 
                                            config.get('local','xmppdomain'))
                self.xmlstream.send( elem )


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
        log.msg('Using cached RSS for room: %s' % (rm,))
        return xml_cache[rm]

    rss = PyRSS2Gen.RSS2(
           generator = "iembot",
           title = "IEMBOT Feed",
           link = "http://mesonet.agron.iastate.edu/iembot-rss/wfo/"+ rm +".xml",
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
        log.msg("Looking for CHATLOG room: %s" % (rm,))
        if not CHATLOG.has_key(rm):
            rss = PyRSS2Gen.RSS2(
            generator = "iembot",
            title = "IEMBOT Feed",
            link = "http://mesonet.agron.iastate.edu/iembot-rss/wfo/"+ tokens[0] +".xml",
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
        #html = "<html><h4>"+ `dir(self.server)` + request.uri +"</h4></html>"
        tokens = re.findall("/room/([a-z0-9]+)",request.uri.lower())
        if (len(tokens) == 0):
            print 'Len tokens is 0'
            request.write( self.wrap(request, json.dumps("ERROR")) )
            request.finish()
            return server.NOT_DONE_YET
        
        room = tokens[0]
        seqnum = int(request.args['seqnum'][0])

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
        self.iembot.join_chatrooms()
        request.write( json.dumps({}) )
        request.finish()
        return server.NOT_DONE_YET

class JSONResource(resource.Resource):
    def __init__(self, iembot):
        resource.Resource.__init__(self)
        self.putChild('room', JsonChannel())
        self.putChild('reload', AdminChannel(iembot))