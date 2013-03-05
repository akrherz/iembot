
from twisted.words.protocols.jabber import jid
from twisted.words.xish import domish, xpath
from twisted.python import log
from twisted.internet.task import LoopingCall
from twisted.words.xish.xmlstream import STREAM_END_EVENT

from twisted.enterprise import adbapi

import random
import ConfigParser
config = ConfigParser.ConfigParser()
config.read('config.ini')

DBPOOL = adbapi.ConnectionPool("psycopg2", database='iem', host='iemdb', 
                               user='nobody',
                               cp_reconnect=True)
   
SUBS = {
        'LMK': ['wbkoweatherwatchers',],
        'PAH': ['wbkoweatherwatchers',],
        'OHX': ['wbkoweatherwatchers','whntweather'],
        'BMX': ['wbkoweatherwatchers','whntweather','abc3340skywatcher',
                'abc3340', 'bmxspotterchat'],
        'HUN': ['wbkoweatherwatchers','whntweather','abc3340skywatcher',
                'abc3340', 'bmxspotterchat'],
        }
    
class APPRISSJabberClient:
    xmlstream = None

    def __init__(self, myJid):
        self.myJid = myJid
        self.seqnum = 0
        self.rooms = []
        self.xmlstream = None
        self.fortunes = open('startrek', 'r').read().split("\n%\n")

    def get_fortune(self):
        """ Get a random value from the array """
        offset = int((len(self.fortunes)-1) * random.random())
        return " ".join( self.fortunes[offset].replace("\n","").split() )

    def keepalive(self):
        if self.xmlstream is not None:
            self.xmlstream.send(' ')

    def authd(self,xmlstream):
        
        log.msg("Logged into APPRISS Chat Server!")
        self.xmlstream = xmlstream
        self.xmlstream.rawDataInFn = self.rawDataInFn
        self.xmlstream.rawDataOutFn = self.rawDataOutFn
        self.xmlstream.addObserver('/message',  self.processMessage)

        presence = domish.Element(('jabber:client','presence'))
        xmlstream.send(presence)

        self.rooms = []
        rooms = ['ABQ', 'AFC', 'AFG', 'AJK', 'AKQ', 'ALY', 'AMA', 'BGM', 'BMX', 
                 'BOI', 'BOU', 'BOX', 'BRO', 'BTV', 'BUF', 'BYZ', 'CAE', 'CAR', 
                 'CHS', 'CRP', 'CTP', 'CYS', 'EKA', 'EPZ', 'EWX', 'KEY', 'FFC', 
                 'FGZ', 'FWD', 'GGW', 'GJT', 'GSP', 'GYX', 'HFO', 'HGX', 'HNX', 
                 'HUN','ILM', 'JAN', 'JAX', 'JKL', 'LCH', 'LIX', 'LKN', 'LMK', 
                 'LOX', 'LUB', 'LWX', 'LZK', 'MAF', 'MEG', 'MFL', 'MFR', 'MHX',
                 'MLB', 'MOB', 'MRX', 'MSO', 'MTR', 'OHX', 'OKX', 'OTX', 'OUN', 
                 'PAH', 'PBZ', 'PDT', 'PHI', 'PIH', 'PQR', 'PSR', 'PUB', 'RAH', 
                 'REV', 'RIW', 'RLX', 'RNK', 'SEW', 'SGX', 'SHV', 'SJT', 'SJU', 
                 'SLC', 'STO', 'TAE', 'TBW', 'TFX', 'TSA', 'TWC', 'VEF', 'ABR', 
                 'APX', 'ARX', 'BIS', 'CLE', 'DDC', 'DLH', 'DTX', 'DVN', 'EAX', 
                 'FGF', 'FSD', 'GID', 'GLD', 'GRB', 'GRR', 'ICT', 'ILN', 'ILX', 
                 'IND', 'IWX', 'LBF', 'LOT', 'LSX', 'MKX', 'MPX', 'MQT', 'OAX', 
                 'SGF', 'TOP', 'UNR', 'DMX','GUM']
        for rm in rooms:
            presence = domish.Element(('jabber:client','presence'))
            presence['to'] = "zz%schat@%s/iembot" % (rm.lower(),
                                                config.get('appriss','muc'))
            xmlstream.send(presence)
            self.rooms.append("zz%schat" % (rm.lower(),))
        rooms = ['wxdump', 'abc3340skywatcher', 'abc3340',
                 'wbkoweatherwatchers', 'whntweather', 'bmxspotterchat']
        for rm in rooms:
            presence = domish.Element(('jabber:client','presence'))
            presence['to'] = "%s@%s/iembot" % (rm, config.get('appriss','muc'))
            xmlstream.send(presence)
            self.rooms.append( rm )
   
        # Keepalive
        lc = LoopingCall(self.keepalive)
        lc.start(60)
        self.xmlstream.addObserver(STREAM_END_EVENT, lambda _: lc.stop())

    def from_iembot(self, elem):
        """ Process a stanza sent to us from the IEMBot instance """
        bstring = xpath.queryForString('/message/body', elem)
        if len(bstring) < 3:
            return

        if elem.x and elem.x.hasAttribute("channels"):
            channels = elem.x['channels'].split(",")
        else:
            # The body string contains
            channel = bstring.split(":", 1)[0]
            channels = [channel,]

        del(elem['from'])
        elem['type'] = "groupchat"
        # Always send to wxdump
        elem['to'] = "wxdump@%s" % (config.get('appriss','muc'),)
        self.xmlstream.send( elem )

        for channel in channels:
            for rm in SUBS.get(channel, []):
                elem['to'] = "%s@%s" % (rm, config.get('appriss','muc'))
                self.xmlstream.send( elem )
            if len(channel) == 3:
                elem['to'] = "zz%schat@%s" % (channel.lower(), 
                                              config.get('appriss','muc'))
                self.xmlstream.send( elem )
                

    def processMessage(self, elem):
        if not elem.hasAttribute("type") or elem['type'] != 'groupchat':
            return

        _from = jid.JID( elem["from"] )
        room = _from.user
        res = _from.resource
        if res is None: 
            return
        
        # If the message is x-delay, old message, no relay
        x = xpath.queryForNodes("/message/x[@xmlns='jabber:x:delay']", elem)
        if x is not None:
            return
        # If it is from some user!
        if res == "iembot":
            return 
        bstring = xpath.queryForString('/message/body', elem)
        # No worky
        if len(bstring) >= 4 and bstring[:4] == "ping":
            self.send_groupchat(room, "%s: %s" % (res, self.get_fortune() ) )
            
        if len(bstring) < 6 or bstring[:7] != "iembot:":
            return
        # We have a command for iembot!
        cmd = bstring[7:].upper().strip()
        tokens = cmd.split()
        if len(tokens) < 2:
            return
        if tokens[0] == "METAR" and len(tokens) == 2:
            if len(tokens[1]) == 4:
                tokens[1] = tokens[1][1:]
            df = DBPOOL.runInteraction( self.send_metar, tokens[1], room)
            df.addErrback( log.err )

    def debug(self, elem):
        log.msg('APP_DEBUG %s' % (elem,))

    def rawDataInFn(self, data):
        if data == ' ':
            return
        log.msg('APP_RECV %s' % (data,))
        
    def rawDataOutFn(self, data):
        if data == ' ':
            return
        log.msg('APP_SEND %s' % (data,))


    def send_groupchat(self, room, mess, html=None):
        """ Send a groupchat message to the desired room """
        message = domish.Element(('jabber:client','message'))
        message['to'] = "%s@%s" % (room, 
                                              config.get('appriss','muc'))
        message['type'] = "groupchat"
        message.addElement('body', None, mess)
        if html is not None:
            message.addRawXml("<html xmlns='http://jabber.org/protocol/xhtml-im'><body xmlns='http://www.w3.org/1999/xhtml'>"+ html +"</body></html>")
        self.xmlstream.send(message)

    def send_metar(self, txn, faaid, room):
        txn.execute("""select raw from current c JOIN stations s 
         ON (s.iemid = c.iemid) WHERE s.id = %s""",  (faaid,) )

        if txn.rowcount == 1:
            row = txn.fetchone()
            self.send_groupchat(room, 'metar: %s' % (row[0],))
        else:
            self.send_groupchat(room, 'Sorry METAR for site %s not found' % (faaid,))









