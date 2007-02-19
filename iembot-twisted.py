#!/usr/bin/env python
# Twisted IEMBot! :)

from twisted.words.protocols.jabber import client, jid, xmlstream
from twisted.words.xish import domish, xpath
from twisted.internet import reactor
from twisted.web import server, xmlrpc
from twisted.internet import reactor
from twisted.python import log

import pdb, mx.DateTime

from secret import *
#log.startLogging( open('twisted.log', 'w') )

CHATLOG = {}

class IEMChatXMLRPC(xmlrpc.XMLRPC):

    def xmlrpc_getUpdate(self, room, seqnum):
        """ Return most recent messages since timestamp (ticks...) """
        #fts = float(timestamp) / 10
     
        #print "XMLRPC-request", room, seqnum, CHATLOG[room]['seqnum']
        r = []
        if (not CHATLOG.has_key(room)):
            return r
        for k in range(len(CHATLOG[room]['seqnum'])):
            if (CHATLOG[room]['seqnum'][k] > seqnum):
                ts = mx.DateTime.DateTimeFromTicks( CHATLOG[room]['timestamps'][k] / 100.0)
                r.append( [ CHATLOG[room]['seqnum'][k] , ts.strftime("%Y%m%d%H%M%S"), CHATLOG[room]['author'][k], CHATLOG[room]['log'][k] ] )
        #print r
        return r


class JabberClient:
    xmlstream = None

    def __init__(self, myJid):
        self.myJid = myJid
        self.seqnum = 0

    def keepalive(self):
        #iq = domish.Element(('', 'iq'))
        #iq['type'] = "get"
        #iq['id'] = "roster_l"
        #q = domish.Element(('jabber:iq:roster', 'query'))
        #iq.addChild(q)
        #self.xmlstream.send(q)
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

        rooms = ['abc3340', 'dmxschoolchat', 'bmxemachat', 'fwdemachat', 'botstalk', 'ABQ', 'AFC', 'AFG', 'AJK', 'AKQ', 'ALY', 'AMA', 'BGM', 'BMX', 'BOI', 'BOU', 'BOX', 'BRO', 'BTV', 'BUF', 'BYZ', 'CAE', 'CAR', 'CHS', 'CRP', 'CTP', 'CYS', 'EKA', 'EPZ', 'EWX', 'KEY', 'FFC', 'FGZ', 'FWD', 'GGW', 'GJT', 'GSP', 'GYX', 'HFO', 'HGX', 'HNX', 'HUN','ILM', 'JAN', 'JAX', 'JKL', 'LCH', 'LIX', 'LKN', 'LMK', 'LOX', 'LUB', 'LWX', 'LZK', 'MAF', 'MEG', 'MFL', 'MFR', 'MHX', 'MLB', 'MOB', 'MRX', 'MSO', 'MTR', 'OHX', 'OKX', 'OTX', 'OUN', 'PAH', 'PBZ', 'PDT', 'PHI', 'PIH', 'PQR', 'PSR', 'PUB', 'RAH', 'REV', 'RIW', 'RLX', 'RNK', 'SEW', 'SGX', 'SHV', 'SJT', 'SJU', 'SLC', 'STO', 'TAE', 'TBW', 'TFX', 'TSA', 'TWC', 'VEF', 'ABR', 'APX', 'ARX', 'BIS', 'CLE', 'DDC', 'DLH', 'DTX', 'DVN', 'EAX', 'FGF', 'FSD', 'GID', 'GLD', 'GRB', 'GRR', 'ICT', 'ILN', 'ILX', 'IND', 'IWX', 'LBF', 'LOT', 'LSX', 'MKX', 'MPX', 'MQT', 'OAX', 'SGF', 'TOP', 'UNR', 'DMX', 'XXX']
        for rm in rooms:
            presence = domish.Element(('jabber:client','presence'))
            presence['to'] = "%s@conference.%s/iembot" % (rm.lower(), CHATSERVER)
            if (len(rm) == 3):
                presence['to'] = "%schat@conference.%s/iembot" % (rm.lower(), CHATSERVER)
            xmlstream.send(presence)



        xmlstream.addObserver('/message',  self.debug)
        xmlstream.addObserver('/message',  self.processMessage)
        xmlstream.addObserver('/iq',  self.debug)
        xmlstream.addObserver('/presence',  self.debug)

    def failure(self, f):
        print f

    def debug(self, elem):
        print elem.toXml().encode('utf-8')
        print "="*20

    def nextSeqnum(self,):
        self.seqnum += 1
        return self.seqnum

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
            if (res is None): res = "---"
            if (not CHATLOG.has_key(room)):
                CHATLOG[room] = {'seqnum': [-1]*40, 'timestamps': [0]*40, 
                                 'log': ['']*40, 'author': ['']*40}
            ticks = int(mx.DateTime.gmt().ticks() * 100)
            x = xpath.queryForNodes('/message/x', elem)
            if (x is not None):
                xdelay = x[0]['stamp']
                print "FOUND Xdelay", xdelay, ":"
                delayts = mx.DateTime.strptime(xdelay, "%Y%m%dT%H:%M:%S")
                ticks = int(delayts.ticks() * 100)

            CHATLOG[room]['seqnum'] = CHATLOG[room]['seqnum'][1:] + [self.nextSeqnum(),]
            CHATLOG[room]['timestamps'] = CHATLOG[room]['timestamps'][1:] + [ticks,]
            CHATLOG[room]['author'] = CHATLOG[room]['author'][1:] + [res,]

            # Go digging for body
            #print "xpath Q:", xpath.queryForString('/message/body', elem)
            html = xpath.queryForNodes('/message/html/body', elem)
            if (html != None):
                CHATLOG[room]['log'] = CHATLOG[room]['log'][1:] + [html[0].toXml(),]
            else:
                try:
                    body = xpath.queryForString('/message/body', elem)
                    CHATLOG[room]['log'] = CHATLOG[room]['log'][1:] + [body,]
                except:
                    print room, 'VERY VERY BAD'

        elif (t == "chat" or t == ""):
            if (_from.userhost() == "iembot_ingest@%s" % (CHATSERVER,) ):
                """ Go look for body to see routing info! """
                wfo = None
                # Get the body string
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
                message['to'] = "botstalk@conference.%s" % (CHATSERVER,)
                message['type'] = "groupchat"
                message.addChild( elem.body )
                if (elem.html):
                    message.addChild(elem.html)
                self.xmlstream.send(message)

                # Send to chatroom, clip body
                message = domish.Element(('jabber:client','message'))
                message['to'] = "%schat@conference.%s" % (wfo.lower(), CHATSERVER,)
                message['type'] = "groupchat"
                message.addElement('body',None,bstring[4:])
                if (elem.html):
                    message.addChild(elem.html)

                self.xmlstream.send(message)
                if (wfo.upper() == "BMX" or wfo.upper() == "FWD"):
                    message['to'] = "%semachat@conference.%s" % (wfo.lower(), CHATSERVER)
                    self.xmlstream.send(message)
                if (wfo.upper() == "BMX" or wfo.upper() == "HUN"):
                    message['to'] = "abc3340@conference.%s" % ( CHATSERVER)
                    self.xmlstream.send(message)
                if (wfo.upper() == "DMX"):
                    message['to'] = "%sschoolchat@conference.%s" % (wfo.lower(), CHATSERVER)
                    self.xmlstream.send(message)
        

myJid = jid.JID('iembot@%s/twisted_words' % (CHATSERVER,) )
factory = client.basicClientFactory(myJid, IEMCHAT_PASS)

jabber = JabberClient(myJid)

factory.addBootstrap('//event/stream/authd',jabber.authd)
factory.addBootstrap("//event/client/basicauth/invaliduser", jabber.failure)
factory.addBootstrap("//event/client/basicauth/authfailed", jabber.failure)
factory.addBootstrap("//event/stream/error", jabber.failure)

#reactor.connectTCP(CHATSERVER,5222,factory)
reactor.connectTCP('jabber2',5222,factory)

xmlrpc = IEMChatXMLRPC()
reactor.listenTCP(8002, server.Site(xmlrpc))


reactor.run()
        
