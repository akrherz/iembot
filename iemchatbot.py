
from twisted.words.protocols.jabber import client, jid, xmlstream
from twisted.words.xish import domish, xpath
from twisted.internet import reactor
from twisted.web import server, xmlrpc
from twisted.python import log

import pdb, mx.DateTime, socket, traceback, random
import StringIO, traceback, smtplib
from email.MIMEText import MIMEText


from secret import *

CHATLOG = {}

CWSU = ['ZAB', 'ZTL', 'ZBW', 'ZAU', 'ZOB', 'ZDV', 'ZFW', 'ZHU',
        'ZID', 'ZKC', 'ZJX', 'ZLA', 'ZME', 'ZMA', 'ZMP', 'ZNY',
        'ZOA', 'ZLC', 'ZSE', 'ZDC']

PRIVATE_ROOMS = ['rgn3fwxchat', 'broemchat', 'wrhchat', 'abqemachat',
                 'jaxemachat', 'bmxalert', 'mlbemchat', 'wxiaweather',
                 'kccichat', 'vipir6and7', 'abc3340', 'dmxemchat',
                 'janhydrochat', 'bmxemachat', 'fwdemachat', 'tbwemchat']

PUBLIC_ROOMS = ['botstalk', 'peopletalk']

WFOS = ['ABQ', 'AFC', 'AFG', 'AJK', 'AKQ', 'ALY', 'AMA', 'BGM', 'BMX',
        'BOI', 'BOU', 'BOX', 'BRO', 'BTV', 'BUF', 'BYZ', 'CAE', 'CAR',
        'CHS', 'CRP', 'CTP', 'CYS', 'EKA', 'EPZ', 'EWX', 'KEY', 'FFC',
        'FGZ', 'FWD', 'GGW', 'GJT', 'GSP', 'GYX', 'HFO', 'HGX', 'HNX',
        'HUN', 'ILM', 'JAN', 'JAX', 'JKL', 'LCH', 'LIX', 'LKN', 'LMK',
        'LOX', 'LUB', 'LWX', 'LZK', 'MAF', 'MEG', 'MFL', 'MFR', 'MHX',
        'MLB', 'MOB', 'MRX', 'MSO', 'MTR', 'OHX', 'OKX', 'OTX', 'OUN',
        'PAH', 'PBZ', 'PDT', 'PHI', 'PIH', 'PQR', 'PSR', 'PUB', 'RAH',
        'REV', 'RIW', 'RLX', 'RNK', 'SEW', 'SGX', 'SHV', 'SJT', 'SJU',
        'SLC', 'STO', 'TAE', 'TBW', 'TFX', 'TSA', 'TWC', 'VEF', 'ABR',
        'APX', 'ARX', 'BIS', 'CLE', 'DDC', 'DLH', 'DTX', 'DVN', 'EAX',
        'FGF', 'FSD', 'GID', 'GLD', 'GRB', 'GRR', 'ICT', 'ILN', 'ILX',
        'IND', 'IWX', 'LBF', 'LOT', 'LSX', 'MKX', 'MPX', 'MQT', 'OAX',
        'SGF', 'TOP', 'UNR', 'DMX', 'GUM']

#o = open('startrek', 'r').read()
#fortunes = o.split("\n%\n")
#cnt_fortunes = len(fortunes)
#del o

def getFortune():
    try:
        offset = int(cnt_fortunes * random.random())
        return fortunes[offset]
    except:
        return ""



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
        presence = domish.Element(('', 'presence'))
        presence.addElement('show').addContent('away')
        presence.addElement('status').addContent('Happy am I, iembot!')
        self.xmlstream.send(presence)

        iq = client.IQ(self.xmlstream, "get")
        iq.addElement(("http://jabber.org/protocol/disco#items", "query"))
        iq.query['node'] = "sessions"
        iq.send()

        socket.setdefaulttimeout(60)
        reactor.callLater(6*60, self.keepalive)

    def rawDataInFn(self, data):
        print 'RECV', unicode(data,'utf-8','ignore').encode('ascii', 'replace')
    def rawDataOutFn(self, data):
        print 'SEND', unicode(data,'utf-8','ignore').encode('ascii', 'replace')

    def authd(self,xmlstream):
        print "Logged into Jabber Chat Server!"
        self.xmlstream = xmlstream
        self.xmlstream.rawDataInFn = self.rawDataInFn
        self.xmlstream.rawDataOutFn = self.rawDataOutFn

        presence = domish.Element(('jabber:client','presence'))
        presence.addElement('status').addContent('Online')
        xmlstream.send(presence)

        self.keepalive()

        for rm in CWSU + PRIVATE_ROOMS + PUBLIC_ROOMS + WFOS:
            presence = domish.Element(('jabber:client','presence'))
            presence['to'] = "%s@conference.%s/iembot" % (rm.lower(), CHATSERVER)
            if (len(rm) == 3):
                presence['to'] = "%schat@conference.%s/iembot" % (rm.lower(), CHATSERVER)
            xmlstream.send(presence)



        #xmlstream.addObserver('/message',  self.debug)
        xmlstream.addObserver('/message',  self.processor)
        #xmlstream.addObserver('/iq',  self.debug)
        #xmlstream.addObserver('/presence',  self.debug)

    def failure(self, f):
        print f

    def debug(self, elem):
        print elem.toXml().encode('utf-8')
        print "="*20

    def nextSeqnum(self,):
        self.seqnum += 1
        return self.seqnum

    def processMessageGC(self, elem):
        _from = jid.JID( elem["from"] )
        room = _from.user
        res = _from.resource
        if (res is None): res = "---"
        if (not CHATLOG.has_key(room)):
            CHATLOG[room] = {'seqnum': [-1]*40, 'timestamps': [0]*40, 
                             'log': ['']*40, 'author': ['']*40}
        ticks = int(mx.DateTime.gmt().ticks() * 100)
        x = xpath.queryForNodes('/message/x', elem)
        if (x is not None and x[0].hasAttribute("stamp") ):
            xdelay = x[0]['stamp']
            print "FOUND Xdelay", xdelay, ":"
            delayts = mx.DateTime.strptime(xdelay, "%Y%m%dT%H:%M:%S")
            ticks = int(delayts.ticks() * 100)
        elif (x is not None):
            print "What is this?", x[0].toXml()

        CHATLOG[room]['seqnum'] = CHATLOG[room]['seqnum'][1:] + [self.nextSeqnum(),]
        CHATLOG[room]['timestamps'] = CHATLOG[room]['timestamps'][1:] + [ticks,]
        CHATLOG[room]['author'] = CHATLOG[room]['author'][1:] + [res,]

        html = xpath.queryForNodes('/message/html/body', elem)
        if (html != None):
            CHATLOG[room]['log'] = CHATLOG[room]['log'][1:] + [html[0].toXml(),]
        else:
            try:
                body = xpath.queryForString('/message/body', elem)
                CHATLOG[room]['log'] = CHATLOG[room]['log'][1:] + [body,]
            except:
                print room, 'VERY VERY BAD'

            #ping pong, sigh!
            # If the message is x-delay, old message, no relay
        try:
            bstring = xpath.queryForString('/message/body', elem)
            if (x is None and len(bstring) >= 4 and bstring[:4] == "ping"):
                message = domish.Element(('jabber:client','message'))
                message['to'] = "%s@conference.%s" %(room,CHATSERVER)
                message['type'] = "groupchat"
                #message.addElement('body',None,"%s: %s"%(res, getFortune()))
                message.addElement('body',None,"%s: %s"%(res, "pong"))
                self.xmlstream.send(message)
            if (x is None and res != "iembot" and room not in PRIVATE_ROOMS+CWSU):
                message = domish.Element(('jabber:client','message'))
                message['to'] = "peopletalk@conference.%s" %(CHATSERVER,)
                message['type'] = "groupchat"
                message.addElement('body',None,"[%s] %s: %s"%(room,res,bstring))
                self.xmlstream.send(message)
        except:
            print traceback.print_exc()

    def processor(self, elem):
        try:
            self.processMessage(elem)
        except:
            io = StringIO.StringIO()
            traceback.print_exc(file=io)
            print io.getvalue() 
            msg = MIMEText("%s\n\n%s\n\n"%(elem.toXml(), io.getvalue() ))
            msg['subject'] = 'iembot Traceback'
            msg['From'] = "ldm@mesonet.agron.iastate.edu"
            msg['To'] = "akrherz@iastate.edu"

            s = smtplib.SMTP()
            s.connect()
            s.sendmail(msg["From"], msg["To"], msg.as_string())
            s.close()


    def processMessage(self, elem):
        t = ""
        try:
            t = elem["type"]
        except:
            print elem.toXml(), 'BOOOOOOO'

        bstring = xpath.queryForString('/message/body', elem)
        if (bstring == ""):
            return

        if (t == "groupchat"):
            self.processMessageGC(elem)

        elif (t == "chat" or t == ""):
            self.processMessagePC(elem)

    def talkWithUser(self, elem):
        _from = jid.JID( elem["from"] )
        message = domish.Element(('jabber:client','message'))
        message['to'] = elem['from']
        message['type'] = "chat"
        message.addElement('body',None,"Sorry, I won't talk back to you yet!")
        self.xmlstream.send(message)

    def processMessagePC(self, elem):
        _from = jid.JID( elem["from"] )

        if (_from.userhost() != "iembot_ingest@%s" % (CHATSERVER,) ):
           self.talkWithUser(elem)
           return

        """ Go look for body to see routing info! """
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
        if (wfo.upper() == "TBW" or wfo.upper() == "MLB"):
            message['to'] = "%semchat@conference.%s" % (wfo.lower(), CHATSERVER)
            self.xmlstream.send(message)
        if (wfo.upper() == "BMX" or wfo.upper() == "FWD"):
            message['to'] = "%semachat@conference.%s" % (wfo.lower(), CHATSERVER)
            self.xmlstream.send(message)
        if (wfo.upper() == "BMX" or wfo.upper() == "HUN"):
            message['to'] = "abc3340@conference.%s" % ( CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "BMX"):
            message['to'] = "bmxalert@conference.%s" % ( CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "MOB" or wfo.upper() == "TAE" or wfo.upper() == "BMX"):
            message['to'] = "vipir6and7@conference.%s" % ( CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "FFC"):
            message['to'] = "wxiaweather@conference.%s" % ( CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "JAN"):
            message['to'] = "janhydrochat@conference.%s" % ( CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "JAX"):
            message['to'] = "jaxemachat@conference.%s" % ( CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "ABQ"):
            message['to'] = "abqemachat@conference.%s" % ( CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "SLC"):
            message['to'] = "wrhchat@conference.%s" % ( CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "BRO"):
            message['to'] = "broemchat@conference.%s" % ( CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "DMX"):
            message['to'] = "%semchat@conference.%s" % (wfo.lower(), CHATSERVER)
            self.xmlstream.send(message)
            message['to'] = "kccichat@conference.%s" % (CHATSERVER,)
            self.xmlstream.send(message)
        

