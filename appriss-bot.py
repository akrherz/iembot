#!/usr/bin/env python
# Twisted IEMBot! :)
# Test

from twisted.words.protocols.jabber import client, jid, xmlstream
from twisted.words.xish import domish, xpath
from twisted.internet import reactor, ssl
from twisted.web import server, xmlrpc
from twisted.internet import reactor
from twisted.python import log

from twisted.enterprise import adbapi
dbpool = adbapi.ConnectionPool("pgdb", database='iem', host='10.10.10.20')

import pdb, mx.DateTime

from secret import *
#log.startLogging( open('twisted.log', 'w') )

CHATLOG = {}

class IEMJabberClient:
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
            # If the message is x-delay, old message, no relay
            x = xpath.queryForNodes('/message/x', elem)
            if (x is not None): return
            # If it is from some user!
            if (res != "iembot"): 
                return


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
            message['to'] = "akrherz@gmail.com"
            message['type'] = "chat"
            gmail.xmlstream.send(message)

            if (wfo.lower() == "bmx" or wfo.lower() == "hun"):
                #message['to'] = "abc3340conference@gmail.com"
                #message['type'] = "chat"
                #gmail.xmlstream.send(message)

                #message['to'] = "abc3340skywatcher@gmail.com"
                #message['type'] = "chat"
                #gmail.xmlstream.send(message)

                message['to'] = "abc3340conference@muc.appriss.com"
                message['type'] = "groupchat"
                appriss.xmlstream.send(message)

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
        presence['to'] = "abc3340conference@muc.appriss.com/iembot"
        xmlstream.send(presence)
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
            print "I FIND bstring: %s room: %s res: %s" % (bstring, room, res)
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

    def nextSeqnum(self,):
        self.seqnum += 1
        return self.seqnum

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
        message.addElement('body',None, l[0][0])
        appriss.xmlstream.send(message)
    else:
        print "No results returned"

apprissJid = jid.JID('iembot@appriss.com/twisted_words')
afactory = client.basicClientFactory(apprissJid, _APPRISS_PASS)
appriss = APPRISSJabberClient(apprissJid)
afactory.addBootstrap('//event/stream/authd',appriss.authd)
afactory.addBootstrap("//event/client/basicauth/invaliduser", appriss.debug)
afactory.addBootstrap("//event/client/basicauth/authfailed", appriss.debug)
afactory.addBootstrap("//event/stream/error", appriss.debug)
reactor.connectTCP('jabber.appriss.com',5222,afactory)

iemJid = jid.JID('iembot2@iemchat.com/twisted_words2')
ifactory = client.basicClientFactory(iemJid, _IEMCHAT_PASS)
iembot = IEMJabberClient(iemJid)
ifactory.addBootstrap('//event/stream/authd',iembot.authd)
ifactory.addBootstrap("//event/client/basicauth/invaliduser", iembot.debug)
ifactory.addBootstrap("//event/client/basicauth/authfailed", iembot.debug)
ifactory.addBootstrap("//event/stream/error", iembot.debug)
reactor.connectTCP('iemchat.com',5222,ifactory)

gmailJid = jid.JID('iemchatbot@gmail.com/twisted_words')
gfactory = client.basicClientFactory(gmailJid, _GMAIL_PASS)
gmail = GMAILJabberClient(gmailJid)
gfactory.addBootstrap('//event/stream/authd',gmail.authd)
gfactory.addBootstrap("//event/client/basicauth/invaliduser", gmail.debug)
gfactory.addBootstrap("//event/client/basicauth/authfailed", gmail.debug)
gfactory.addBootstrap("//event/stream/error", gmail.debug)
cix = ssl.ClientContextFactory()
reactor.connectSSL('talk.google.com',5223,gfactory, cix)


reactor.run()
        
