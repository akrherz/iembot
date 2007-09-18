#!/usr/bin/env python
# Twisted IEMBot! :)
# Test

from twisted.words.protocols.jabber import client, jid, xmlstream
from twisted.words.xish import domish, xpath
from twisted.internet import reactor
from twisted.web import server, xmlrpc, resource
from twisted.internet import reactor
from twisted.python import log


from twisted.enterprise import adbapi
dbpool = adbapi.ConnectionPool("psycopg2", database='iem', host='10.10.10.20')

import pdb, mx.DateTime, datetime, re

from secret import *
#log.startLogging( open('twisted.log', 'w') )

import PyRSS2Gen

CHATLOG = {}

def add2chatlog(res, elem):
    x = xpath.queryForNodes('/message/x', elem)
    bstring = xpath.queryForString('/message/body', elem)
    if (len(bstring) < 3):
        return
    myrm = "%schat" % (bstring[:3].lower(),)

    ticks = int(mx.DateTime.gmt().ticks() * 100)
    if (x is not None and x[0].hasAttribute("stamp") ):
        xdelay = x[0]['stamp']
        log.msg("FOUND Xdelay %s:" % ( xdelay,) )
        delayts = mx.DateTime.strptime(xdelay, "%Y%m%dT%H:%M:%S")
        ticks = int(delayts.ticks() * 100)

    html = xpath.queryForNodes('/message/html/body', elem)
    body = xpath.queryForString('/message/body', elem)
    if (html != None):
        logEntry = html[0].toXml()
    else:
        try:
            logEntry = body
        except:
            print realroom, 'VERY VERY BAD'
    for rm in [myrm, "botstalk"]:
        if (not CHATLOG.has_key(rm)):
            CHATLOG[rm] = {'seqnum': [-1]*40, 'timestamps': [0]*40,
              'txtlog': ['']*40, 'log': ['']*40, 'author': ['']*40}
        CHATLOG[rm]['seqnum'] = CHATLOG[rm]['seqnum'][1:] + [iembot.nextSeqnum(),]
        CHATLOG[rm]['timestamps'] = CHATLOG[rm]['timestamps'][1:] + [ticks,]
        CHATLOG[rm]['author'] = CHATLOG[rm]['author'][1:] + [res,]
        CHATLOG[rm]['log'] = CHATLOG[rm]['log'][1:] + [logEntry,]
        CHATLOG[rm]['txtlog'] = CHATLOG[rm]['txtlog'][1:] + [body[4:],]

class IEMJabberClient:
    xmlstream = None

    def __init__(self, myJid):
        self.myJid = myJid
        self.seqnum = 0

    def nextSeqnum(self,):
        self.seqnum += 1
        return self.seqnum

    def keepalive(self):
        presence = domish.Element(('', 'presence'))
        presence['show'] = "away"
        presence['priority'] = "1"
        presence['status'] = "I am iembot, hear me roar"
        self.xmlstream.send(presence)
        reactor.callLater(6*60, self.keepalive)

    def authd(self,xmlstream):
        print "Logged into Jabber Chat Server!"
        self.xmlstream = xmlstream
        presence = domish.Element(('jabber:client','presence'))
        xmlstream.send(presence)

        self.keepalive()
        presence = domish.Element(('jabber:client','presence'))
        presence['to'] = "botstalk@conference.iemchat.com/appriss" 
        xmlstream.send(presence)

        xmlstream.addObserver('/message',  self.debug)
        xmlstream.addObserver('/message',  self.processMessage)
        xmlstream.addObserver('/iq',  self.debug)
        xmlstream.addObserver('/presence',  self.debug)

    def debug(self, elem):
        print elem.toXml().encode('utf-8')
        print "="*20


    # Take messages in the room from iembot and send them over
    def processMessage(self, elem):
        _from = jid.JID( elem["from"] )
        t = ""
        try:
            t = elem["type"]
        except:
            print elem.toXml(), 'BOOOOOOO'

        if (t == "groupchat"):
            #print elem.toXml(), '----', str(elem.children), '---'
            room = _from.user
            res = _from.resource
            if (res is None): return
            # If it is from some user!
            if (res != "iembot"): 
                return
            add2chatlog(res, elem)
            # If the message is x-delay, old message, no relay
            x = xpath.queryForNodes('/message/x', elem)
            if (x is not None): return



            bstring = xpath.queryForString('/message/body', elem)
            htmlstr = xpath.queryForString('/message/html/body', elem)
            if (len(bstring) < 3):
                print "BAD!!!"
                return
            wfo = bstring[:3]
            # Look for HTML
            html = xpath.queryForNodes('/message/html', elem)

 



            # Route message to botstalk room in tact
            message = domish.Element(('jabber:client','message'))
            message.addChild( elem.body )
            if (elem.html):
                message.addChild(elem.html)

            #print "Fire Google Talk!!!"
            #message['to'] = "akrherz@gmail.com"
            #message['type'] = "chat"
            #gmail.xmlstream.send(message)

            if (wfo.lower() == "bmx" or wfo.lower() == "hun"):
                #message['to'] = "abc3340conference@gmail.com"
                #message['type'] = "chat"
                #gmail.xmlstream.send(message)

                #message['to'] = "abc3340skywatcher@gmail.com"
                #message['type'] = "chat"
                #gmail.xmlstream.send(message)

                #message['to'] = "abc3340conference@muc.appriss.com"
                #message['type'] = "groupchat"
                #appriss.xmlstream.send(message)

                message['to'] = "abc3340skywatcher@muc.appriss.com"
                message['type'] = "groupchat"
                appriss.xmlstream.send(message)

            message['to'] = "zz%schat@muc.appriss.com" % (wfo.lower(),)
            message['type'] = "groupchat"
            appriss.xmlstream.send(message)

            message['to'] = "wxdump@muc.appriss.com"
            message['type'] = "groupchat"
            appriss.xmlstream.send(message)

class GMAILJabberClient:
    xmlstream = None

    def __init__(self, myJid):
        self.myJid = myJid
        self.seqnum = 0

    def keepalive(self):
        presence = domish.Element(('', 'presence'))
        presence['show'] = "away"
        presence['priority'] = "1"
        presence['status'] = "I am iembot, hear me roar"
        self.xmlstream.send(presence)
        reactor.callLater(6*60, self.keepalive)

    def authd(self,xmlstream):
        print "Logged into Google Talk!"
        self.xmlstream = xmlstream
        presence = domish.Element(('jabber:client','presence'))
        xmlstream.send(presence)

        self.keepalive()


        xmlstream.addObserver('/message',  self.debug)
        xmlstream.addObserver('/iq',  self.debug)
        xmlstream.addObserver('/presence',  self.debug)

    def debug(self, elem):
        print elem.toXml().encode('utf-8')
        print "Google Talk ", "="*20

class APPRISSJabberClient:
    xmlstream = None

    def __init__(self, myJid):
        self.myJid = myJid
        self.seqnum = 0

    def keepalive(self):
        presence = domish.Element(('', 'presence'))
        presence['show'] = "away"
        presence['priority'] = "1"
        presence['status'] = "I am iembot, hear me roar"
        self.xmlstream.send(presence)
        reactor.callLater(6*60, self.keepalive)

    def authd(self,xmlstream):
        print "Logged into Jabber Chat Server!"
        self.xmlstream = xmlstream
        presence = domish.Element(('jabber:client','presence'))
        xmlstream.send(presence)

        #self.keepalive()

        rooms = ['ABQ', 'AFC', 'AFG', 'AJK', 'AKQ', 'ALY', 'AMA', 'BGM', 'BMX', 'BOI', 'BOU', 'BOX', 'BRO', 'BTV', 'BUF', 'BYZ', 'CAE', 'CAR', 'CHS', 'CRP', 'CTP', 'CYS', 'EKA', 'EPZ', 'EWX', 'KEY', 'FFC', 'FGZ', 'FWD', 'GGW', 'GJT', 'GSP', 'GYX', 'HFO', 'HGX', 'HNX', 'HUN','ILM', 'JAN', 'JAX', 'JKL', 'LCH', 'LIX', 'LKN', 'LMK', 'LOX', 'LUB', 'LWX', 'LZK', 'MAF', 'MEG', 'MFL', 'MFR', 'MHX', 'MLB', 'MOB', 'MRX', 'MSO', 'MTR', 'OHX', 'OKX', 'OTX', 'OUN', 'PAH', 'PBZ', 'PDT', 'PHI', 'PIH', 'PQR', 'PSR', 'PUB', 'RAH', 'REV', 'RIW', 'RLX', 'RNK', 'SEW', 'SGX', 'SHV', 'SJT', 'SJU', 'SLC', 'STO', 'TAE', 'TBW', 'TFX', 'TSA', 'TWC', 'VEF', 'ABR', 'APX', 'ARX', 'BIS', 'CLE', 'DDC', 'DLH', 'DTX', 'DVN', 'EAX', 'FGF', 'FSD', 'GID', 'GLD', 'GRB', 'GRR', 'ICT', 'ILN', 'ILX', 'IND', 'IWX', 'LBF', 'LOT', 'LSX', 'MKX', 'MPX', 'MQT', 'OAX', 'SGF', 'TOP', 'UNR', 'DMX','XXX']
        for rm in rooms:
            presence = domish.Element(('jabber:client','presence'))
            presence['to'] = "zz%schat@muc.appriss.com/iembot" % (rm.lower(),)
            xmlstream.send(presence)
        presence = domish.Element(('jabber:client','presence'))
        presence['to'] = "wxdump@muc.appriss.com/iembot"
        xmlstream.send(presence)
        #presence['to'] = "abc3340conference@muc.appriss.com/iembot"
        #xmlstream.send(presence)
        presence['to'] = "abc3340skywatcher@muc.appriss.com/iembot"
        xmlstream.send(presence)


        xmlstream.addObserver('/iq',  self.debug)
        xmlstream.addObserver('/presence',  self.debug)
        xmlstream.addObserver('/message',  self.processMessage)

    def processMessage(self, elem):
        _from = jid.JID( elem["from"] )
        t = ""
        try:
            t = elem["type"]
        except:
            print elem.toXml(), 'BOOOOOOO'

        if (t == "groupchat"):
            #print elem.toXml(), '----', str(elem.children), '---'
            room = _from.user
            res = _from.resource
            if (res is None): return
            # If the message is x-delay, old message, no relay
            x = xpath.queryForNodes('/message/x', elem)
            if (x is not None): return
            # If it is from some user!
            if (res == "iembot"):
                return 
            bstring = xpath.queryForString('/message/body', elem)
            # No worky
            #print "I FIND bstring: %s room: %s res: %s" % (unicode(bstring,'utf-8','ignore').encode('ascii', 'replace'), room, res)
            if (len(bstring) >= 4 and bstring[:4] == "ping"):
                message = domish.Element(('jabber:client','message'))
                message['to'] = "%s@muc.appriss.com" %(room,)
                message['type'] = "groupchat"
                message.addElement('body',None,"%s: pong"%(res,))
                self.xmlstream.send(message)
                
            if (len(bstring) < 6 or bstring[:7] != "iembot:"):
                return
            # We have a command for iembot!
            cmd = bstring[7:].upper().strip()
            tokens = cmd.split()
            if (len(tokens) < 2):
               return
            if (tokens[0] == "METAR" and len(tokens) == 2):
               if (len(tokens[1]) == 4):
                  tokens[1] = tokens[1][1:]
               getMETAR( tokens[1] ).addCallback(sendMETAR, room).addErrback(errHandler)


    def debug(self, elem):
        print elem.toXml().encode('utf-8')
        print "="*20


def errHandler(reason):
    print reason

def getMETAR(id):
    return dbpool.runQuery("select raw from current WHERE station = '%s'" % (id,) )

def sendMETAR(l, room):
    if l:
        print l[0][0], "years old"
        message = domish.Element(('jabber:client','message'))
        message['to'] = "%s@muc.appriss.com" %(room,)
        message['type'] = "groupchat"
        message.addElement('body',None, 'metar: '+ l[0][0])
        appriss.xmlstream.send(message)
    else:
        print "No results returned"


class IEMChatXMLRPC(xmlrpc.XMLRPC):

    def xmlrpc_getUpdate(self, room, seqnum):
        """ Return most recent messages since timestamp (ticks...) """
        #fts = float(timestamp) / 10
     
        #print "XMLRPC-request", room, seqnum, CHATLOG[room]['seqnum']
        r = []
        if (not CHATLOG.has_key(room)):
            if (seqnum == 0):
                r.append( [1, mx.DateTime.gmt().strftime("%Y%m%d%H%M%S"), "iembot", "No messages accumulated yet"] )
            return r
        for k in range(len(CHATLOG[room]['seqnum'])):
            if (CHATLOG[room]['seqnum'][k] > seqnum):
                ts = mx.DateTime.DateTimeFromTicks( CHATLOG[room]['timestamps'][k] / 100.0)
                r.append( [ CHATLOG[room]['seqnum'][k] , ts.strftime("%Y%m%d%H%M%S"), CHATLOG[room]['author'][k], CHATLOG[room]['log'][k] ] )
        return r

def fdate(dt):
    return "%s, %02d %s %04d %02d:%02d:%02d GMT" % (
            ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][dt.day_of_week],
            dt.day,
            ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][dt.month-1],
            dt.year, dt.hour, dt.minute, dt.second)

xml_cache = {}
xml_cache_expires = {}

def wfoRSS(rm):
    if (not xml_cache.has_key(rm)):
      xml_cache[rm] = ""
      xml_cache_expires[rm] = -2


    lastID = CHATLOG[rm]['seqnum'][-1]
    if (lastID == xml_cache_expires[rm]):
      print 'Cached XML used',rm
      return xml_cache[rm]


    rss = PyRSS2Gen.RSS2(
           generator = "iembot",
           title = "IEMBOT Feed",
           link = "http://mesonet.agron.iastate.edu/iembot-rss/wfo/"+ rm +".xml",
           description = "To much fun!",
           lastBuildDate = datetime.datetime.utcnow() )

    for k in range(len(CHATLOG[rm]['seqnum'])-1,-1,-1 ):
       if CHATLOG[rm]['seqnum'][k] < 0:
           continue
       ts = mx.DateTime.DateTimeFromTicks( CHATLOG[rm]['timestamps'][k] / 100.0)
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
            pubDate = fdate(ts) ) )

    xml_cache[rm] = rss.to_xml()
    xml_cache_expires[rm] = lastID
    return rss.to_xml()

class HomePage(resource.Resource):
    def isLeaf(self): return true
    def __init__(self):
        resource.Resource.__init__(self)

    def render(self, request):
        #html = "<html><h4>"+ `dir(self.server)` + request.uri +"</h4></html>"
        tokens = re.findall("/wfo/k(...).xml",request.uri.lower())
        if (len(tokens) == 0):
           return "ERROR!"
        
        rm = "%schat" % (tokens[0],)
        if (not CHATLOG.has_key(rm)):
            rss = PyRSS2Gen.RSS2(
            generator = "iembot",
            title = "IEMBOT Feed",
            link = "http://mesonet.agron.iastate.edu/iembot-rss/wfo/"+ rm +".xml",
            description = "To much fun!",
            lastBuildDate = datetime.datetime.utcnow() )
            rss.items.append( 
              PyRSS2Gen.RSSItem(
               title = "IEMBOT resently restarted, no history yet",
               link =  "http://mesonet.agron.iastate.edu/projects/iembot/",
               pubDate =  datetime.datetime.utcnow() ) )
            xml = rss.to_xml()
        else:
            xml = wfoRSS(rm )
        request.setHeader('Content-Length', len(xml))
        request.setHeader('Content-Type', 'text/xml')
        request.setResponseCode(200)
        request.write( xml )
        request.finish()
        return server.NOT_DONE_YET


class RootResource(resource.Resource):
    def __init__(self):
        resource.Resource.__init__(self)
        self.putChild('wfo', HomePage())



apprissJid = jid.JID('iembot@appriss.com/twisted_words')
afactory = client.basicClientFactory(apprissJid, APPRISS_PASS)
appriss = APPRISSJabberClient(apprissJid)
afactory.addBootstrap('//event/stream/authd',appriss.authd)
afactory.addBootstrap("//event/client/basicauth/invaliduser", appriss.debug)
afactory.addBootstrap("//event/client/basicauth/authfailed", appriss.debug)
afactory.addBootstrap("//event/stream/error", appriss.debug)
reactor.connectTCP('jabber.appriss.com',5222,afactory)

iemJid = jid.JID('iembot2@iemchat.com/twisted_words22')
ifactory = client.basicClientFactory(iemJid, IEMCHAT_PASS)
iembot = IEMJabberClient(iemJid)
ifactory.addBootstrap('//event/stream/authd',iembot.authd)
ifactory.addBootstrap("//event/client/basicauth/invaliduser", iembot.debug)
ifactory.addBootstrap("//event/client/basicauth/authfailed", iembot.debug)
ifactory.addBootstrap("//event/stream/error", iembot.debug)
reactor.connectTCP('iemchat.com',5222,ifactory)

"""
gmailJid = jid.JID('iemchatbot@gmail.com/twisted_words')
gfactory = client.basicClientFactory(gmailJid, GMAIL_PASS)
gmail = GMAILJabberClient(gmailJid)
gfactory.addBootstrap('//event/stream/authd',gmail.authd)
gfactory.addBootstrap("//event/client/basicauth/invaliduser", gmail.debug)
gfactory.addBootstrap("//event/client/basicauth/authfailed", gmail.debug)
gfactory.addBootstrap("//event/stream/error", gmail.debug)
cix = ssl.ClientContextFactory()
reactor.connectSSL('talk.google.com',5223,gfactory, cix)
"""

xmlrpc = IEMChatXMLRPC()
reactor.listenTCP(8003, server.Site(xmlrpc))

w = server.Site(RootResource())
reactor.listenTCP(8004, w)

reactor.run()
