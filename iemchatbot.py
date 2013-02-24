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
""" Chat bot implementation for NWSChat """

from twisted.words.protocols.jabber import client, jid
from twisted.words.xish import domish, xpath
from twisted.web import xmlrpc, client
from twisted.mail import smtp
from twisted.python import log
from twisted.python.logfile import DailyLogFile
from twisted.enterprise import adbapi
from twisted.words.xish.xmlstream import STREAM_END_EVENT
from twisted.internet.task import LoopingCall
from twisted.internet import reactor

import mx.DateTime, socket, re, md5
import StringIO, traceback, base64, urllib
from email.MIMEText import MIMEText

import ConfigParser
config = ConfigParser.ConfigParser()
config.read('config.ini')

CHATLOG = {}
ROSTER = {}


CWSU = ['zabchat', 'ztlchat', 'zbwchat', 'zauchat', 'zobchat', 
        'zdvchat', 'zfwchat', 'zhuchat', 'zidchat', 'zkcchat', 
        'zjxchat', 'zlachat', 'zmechat', 'zmachat', 'zmpchat', 
        'znychat', 'zoachat', 'zlcchat', 'zsechat', 'zdcchat',
        'zanchat']

RFC_ROOMS = ['abrfcchat', 'aprfcchat', 'cnrfcchat', 'cbrfcchat',
             'marfcchat', 'mbrfcchat', 'lmrfcchat', 'ncrfcchat',
             'nerfcchat', 'nwrfcchat', 'ohrfcchat', 'serfcchat',
             'wgrfcchat']
ER_PRIVATE_ROOMS = []
PR_PRIVATE_ROOMS = []
AR_PRIVATE_ROOMS = ['redoubtchat', 'aawuchat']
SR_PRIVATE_ROOMS = ['broemchat', 'abqemachat', 'jaxemachat', 'bmxalert',
                    'mlbemchat', 'ounemchat', 'hgxemachat', 'janhydrochat',
                    'bmxemachat', 'fwdemachat', 'tbwemchat', 'tbwnetchat',
                    'tbwhamchat', 'ekaemachat', 'tsaemachat', 'mafskywarn']
CR_PRIVATE_ROOMS = ['dmxemachat', 'iaseocchat', 'dvnemachat', 'ilxhamchat',
                    'sdeoc', 'apxfwxchat', 'apxemachat', 'lsxemachat']
WR_PRIVATE_ROOMS = ['pspcchat', 'pubemachat', 'sewemachat']
OT_PRIVATE_ROOMS = ['rgn3fwxchat', 'abc3340', 'wdtbchat', 'spaceflightmet',
                 'allpeopletalk', 'ncrfcagencieschat']
PRIVATE_ROOMS = OT_PRIVATE_ROOMS + WR_PRIVATE_ROOMS + CR_PRIVATE_ROOMS + SR_PRIVATE_ROOMS + ER_PRIVATE_ROOMS + PR_PRIVATE_ROOMS + AR_PRIVATE_ROOMS

PUBLIC_ROOMS = ['botstalk', 'peopletalk',
                'crbotstalk', 'wrbotstalk', 'prbotstalk',
                'srbotstalk', 'erbotstalk', 'arbotstalk',
                'crpeopletalk', 'wrpeopletalk', 'prpeopletalk',
                'srpeopletalk', 'erpeopletalk', 'arpeopletalk']

CR_WFOS = ['gjtchat', 'jklchat', 'dmxchat',
           'dtxchat', 'dvnchat', 'eaxchat', 'fgfchat', 'fsdchat', 'gidchat',
           'gldchat', 'grbchat', 'grrchat', 'ictchat', 'ilnchat', 'ilxchat',
           'indchat', 'iwxchat', 'lbfchat', 'lotchat', 'lsxchat', 'mkxchat',
           'mpxchat', 'mqtchat', 'oaxchat', 'sgfchat', 'topchat', 'unrchat',
           'lmkchat', 'pahchat', 'abrchat', 'apxchat', 'arxchat', 'bischat',
           'ddcchat', 'dlhchat']
SR_WFOS = ['abqchat', 'amachat', 'bmxchat', 'brochat', 'crpchat', 'epzchat',
           'ewxchat', 'keychat', 'ffcchat', 'fwdchat', 'hgxchat', 'hunchat',
           'janchat', 'jaxchat', 'lchchat', 'gumchat', 'lixchat', 'lubchat',
           'lzkchat', 'mafchat', 'megchat', 'mflchat', 'mlbchat', 'mobchat',
           'mrxchat', 'ohxchat', 'ounchat', 'rahchat', 'shvchat', 'sjtchat',
           'sjuchat', 'taechat', 'tbwchat', 'tsachat']
PR_WFOS = ['afcchat', 'afgchat', 'ajkchat']
AR_WFOS = ['hfochat',]
ER_WFOS = ['akqchat', 'alychat', 'bgmchat', 'boxchat', 'btvchat', 'bufchat',
           'caechat', 'carchat', 'chschat', 'ctpchat', 'gspchat', 'gyxchat',
           'ilmchat', 'lwxchat', 'mhxchat', 'msochat', 'mtrchat', 'okxchat',
           'pbzchat', 'phichat', 'rlxchat', 'rnkchat', 'clechat']
WR_WFOS = ['boichat', 'bouchat', 'byzchat', 'cyschat', 'ekachat', 'fgzchat',
           'ggwchat', 'hnxchat', 'lknchat', 'loxchat', 'mfrchat', 'otxchat',
           'pdtchat', 'pihchat', 'pqrchat', 'psrchat', 'pubchat', 'revchat',
           'riwchat', 'sewchat', 'sgxchat', 'slcchat', 'stochat', 'tfxchat',
           'twcchat', 'vefchat']
WFOS = CR_WFOS + SR_WFOS + PR_WFOS + ER_WFOS + WR_WFOS + AR_WFOS

CR_ROOMS = CR_WFOS + CR_PRIVATE_ROOMS
SR_ROOMS = SR_WFOS + SR_PRIVATE_ROOMS
ER_ROOMS = ER_WFOS + ER_PRIVATE_ROOMS
WR_ROOMS = WR_WFOS + WR_PRIVATE_ROOMS
AR_ROOMS = AR_WFOS + AR_PRIVATE_ROOMS
PR_ROOMS = PR_WFOS + PR_PRIVATE_ROOMS

ROUTES = {
  'TBW': ['tbwnetchat', 'tbwhamchat', 'tbwemchat'],
  'MLB': ['mlbemchat'],
  'BMX': ['bmxemachat', 'bmxalert'],
  'FWD': ['fwdemachat'],
  'JAN': ['janhydrochat'],
  'JAX': ['jaxemachat'],
  'LSX': ['lsxemachat'],
  'ABQ': ['abqemachat'],
  'OUN': ['ounemchat'],
  'BRO': ['broemchat'],
  'DMX': ['dmxemachat'],
  'APX': ['apxemachat', 'apxfwxchat'],
  'EKA': ['ekaemachat'],
  'PUB': ['pubemachat'],
  'DVN': ['dvnemachat'],
  'TSA': ['tsaemachat'],
  'HGX': ['hgxemachat'],
  'SEW': ['sewemachat'],
  'ILX': ['ilxhamchat'],
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
  'AWU': ['redoubtchat'],
  'MAF': ['mafskywarn'],
}

PHONE_RE = re.compile(r'(\d{3})\D*(\d{3})\D*(\d{4})\D*(\d*)')



class JabberClient:
    xmlstream = None
    MAIL_COUNT = 10
    myname = "iembot"

    def __init__(self, myJid):
        self.myJid = myJid
        self.handle = myJid.user
        self.seqnum = 0



    def send_presence(self):
        presence = domish.Element(('jabber:client','presence'))
        presence.addElement('status').addContent('At your service...')
        self.xmlstream.send(presence)

        socket.setdefaulttimeout(60)

    def keepalive(self):
        """ Whitespace ping for now... Openfire < 3.6.0 does not 
            support XMPP-Ping
        """
        if (self.xmlstream is not None):
            self.xmlstream.send(' ')


    def rawDataInFn(self, data):
        print 'RECV', unicode(data,'utf-8','ignore').encode('ascii', 'replace')
    def rawDataOutFn(self, data):
        if (data == ' '):
            return
        print 'SEND', unicode(data,'utf-8','ignore').encode('ascii', 'replace')

    def authd(self, xmlstream):
        print "Logged into Jabber Chat Server!"
        self.xmlstream = xmlstream
        self.xmlstream.rawDataInFn = self.rawDataInFn
        self.xmlstream.rawDataOutFn = self.rawDataOutFn

        self.xmlstream.addObserver('/message',  self.processor)
        self.xmlstream.addObserver('/presence/x/item',  self.presence_processor)


        self.send_presence()
        self.join_chatrooms()
        lc = LoopingCall(self.keepalive)
        lc.start(60)
        self.xmlstream.addObserver(STREAM_END_EVENT, lambda _: lc.stop())

    def join_chatrooms(self):
        cnt = 0
        for rm in CWSU + PRIVATE_ROOMS + PUBLIC_ROOMS + WFOS + RFC_ROOMS:
            ROSTER[rm] = {}
            presence = domish.Element(('jabber:client','presence'))
            presence['to'] = "%s@conference.%s/%s" % (rm, config.get('local','xmppdomain'), self.handle)
            reactor.callLater(cnt % 20, self.xmlstream.send, presence)
            cnt += 1

    def daily_timestamp(self):
        """  Send the timestamp into each room, each GMT day... """
        # Make sure we are a bit into the future!
        ts = mx.DateTime.gmt() + mx.DateTime.RelativeDateTime(hours=1)
        mess = "------ %s [GMT] ------" % (ts.strftime("%b %d, %Y"),)
        for rm in CWSU + PRIVATE_ROOMS + PUBLIC_ROOMS + WFOS + RFC_ROOMS:
            self.send_groupchat(rm, mess)

        tnext = ts + mx.DateTime.RelativeDateTime(hour=0,days=1,minute=0,second=0)
        print 'Calling daily_timestamp in %s seconds' % ((tnext - mx.DateTime.gmt()).seconds, )
        reactor.callLater( (tnext - mx.DateTime.gmt()).seconds, self.daily_timestamp)

    def presence_processor(self, elem):
        """ Process presence items
        <presence to="iembot@localhost/twisted_words" 
                  from="gumchat@conference.localhost/iembot">
         <x xmlns="http://jabber.org/protocol/muc#user">
          <item jid="iembot@localhost/twisted_words" affiliation="none" 
                role="participant"/>
         </x>
        </presence>
        """
        _room = jid.JID( elem["from"] ).user
        _handle = jid.JID( elem["from"] ).resource
        items = xpath.queryForNodes('/presence/x/item', elem)
        if (items is None):
            return
        for item in items:
            if (item.attributes.has_key('jid') and
                item.attributes.has_key('affiliation') and 
                item.attributes.has_key('role') ):
                if (item.attributes['role'] == "none"):
                    if ( ROSTER[_room].has_key(_handle) ):
                        del( ROSTER[_room][_handle] )
                else:
                    ROSTER[ _room ][ _handle ] = {
                      'jid': item.attributes['jid'],
                      'affiliation': item.attributes['affiliation'],
                      'role': item.attributes['role'] }

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

        # If the message is x-delay, old message, no relay
        if (x is not None):
            return
        bstring = xpath.queryForString('/message/body', elem)

        if (res == self.handle):
            return

        # Send a copy of the message to the peopletalk room
        # TODO: support sending the HTML variant
        if room in WFOS:
            self.send_groupchat("peopletalk", "[%s] %s: %s"%(room,res,bstring))
        if room in CR_ROOMS:
            self.send_groupchat("crpeopletalk", "[%s] %s: %s"%(room,res,bstring))
        elif room in AR_ROOMS:
            self.send_groupchat("arpeopletalk", "[%s] %s: %s"%(room,res,bstring))
        elif room in SR_ROOMS:
            self.send_groupchat("srpeopletalk", "[%s] %s: %s"%(room,res,bstring))
        elif room in WR_ROOMS:
            self.send_groupchat("wrpeopletalk", "[%s] %s: %s"%(room,res,bstring))
        elif room in PR_ROOMS:
            self.send_groupchat("prpeopletalk", "[%s] %s: %s"%(room,res,bstring))
        elif room in ER_ROOMS:
            self.send_groupchat("erpeopletalk", "[%s] %s: %s"%(room,res,bstring))

        # Send a copy of the message to the allpeopletalk room
        self.send_groupchat("allpeopletalk", "[%s] %s: %s"%(room,res,bstring))

        # Look for bot commands
        if re.match(r"^%s:" % (self.handle,), bstring):
            self.process_groupchat_cmd(room, res, bstring[7:].strip())

        # Look for legacy ping
        if re.match(r"^ping", bstring):
            self.process_groupchat_cmd(room, res, "ping")



    def process_groupchat_cmd(self, room, res, cmd):
        """ I actually process the groupchat commands and do stuff """
        if (not ROSTER[room].has_key(res)):
            self.send_groupchat(room, "%s: I don't know who are!"%(res,))
            return
        aff = ROSTER[room][res]['affiliation']

        # Look for sms request
        if re.match(r"^sms", cmd.lower()):
            # Make sure the user is an owner or admin, I think
            if (aff in ['owner','admin']):
                self.process_sms(room, cmd[3:], ROSTER[room][res]['jid'])
            else:
                err = "%s: Sorry, you must be a room admin to send a SMS" \
                       % (res,)
                self.send_groupchat(room, err)

        elif re.match(r"^email", cmd.lower()):
            # Make sure the user is an owner or admin, I think
            if (aff in ['owner','admin']):
                self.send_group_email(room, cmd[5:], ROSTER[room][res]['jid'])
            else:
                err = "%s: Sorry, you must be a room admin to send an email" \
                       % (res,)
                self.send_groupchat(room, err)


        # Look for users request
        elif re.match(r"^users", cmd.lower()):
            rmess = ""
            for hndle in ROSTER[room].keys():
                rmess += "%s (%s), " % (hndle, ROSTER[room][hndle]['jid'],)
            if (aff in ['owner','admin']):
                self.send_privatechat(ROSTER[room][res]['jid'], "JIDs in room: %s" % (rmess,))
            else:
                err = "%s: Sorry, you must be a room admin to query users" \
                       % (res,)
                self.send_groupchat(room, err)

        # Look for users request
        elif re.match(r"^ping", cmd.lower()):
            self.send_groupchat(room, "%s: %s"%(res, "pong"))

        # Else send error message about what I support
        else:
            err = """Unsupported command: '%s'
Current Supported Commands:
  %s: sms My SMS message to send     ### Send SMS Message to this Group
  %s: email My email message to send ### Send Email to this Group
  %s: ping          ### Test connectivity with a 'pong' response
  %s: users         ### Generates list of users in room""" % (cmd, 
            self.handle, self.handle, self.handle, self.handle)
            htmlerr = err.replace("\n", "<br />").replace("Supported Commands"\
      ,"<a href=\"https://%s/nws/%s.php\">Supported Commands</a>" % \
            (config.get('local','xmppdomain'), self.myname) )
            self.send_groupchat(room, err, htmlerr)



    def processor(self, elem):
        try:
            self.processMessage(elem)
        except:
            self.MAIL_COUNT -= 1
            if self.MAIL_COUNT < 0:
                print "LIMIT MAIL_COUNT"
                return
            io = StringIO.StringIO()
            traceback.print_exc(file=io)
            print io.getvalue() 
            msg = MIMEText("%s\n\n%s\n\n"%(elem.toXml(), io.getvalue() ))
            msg['subject'] = '%s Traceback' % (self.handle,)
            msg['From'] = "ldm@%s" % (config.get('local','xmppdomain'),)
            msg['To'] = "akrherz@iastate.edu"

            smtp.sendmail("localhost", msg["From"], msg["To"], msg)


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
        bstring = xpath.queryForString('/message/body', elem)
        if (bstring is None):
            print "Empty conversation?", elem.toXml()
            return 

        bstring = bstring.lower()
        if re.match(r"^set sms#", bstring):
            self.handle_sms_request( elem, bstring)
        elif re.match(r"^cs[0-9]+", bstring):
            self.confirm_sms( elem, bstring)
        else:
            self.send_help_message( elem["from"] )

    def send_help_message(self, to):
        msg = """Hi, I am %s.  You can try talking directly with me.
Currently supported commands are:
  set sms# 555-555-5555  (command will set your SMS number)
  set sms# 0             (disables SMS messages from NWSChat)""" % (self.handle,)
        htmlmsg = msg.replace("\n","<br />").replace(self.handle, \
                 "<a href=\"https://%s/nws/%s.php\">%s</a>" % \
                 (config.get('local','xmppdomain'), self.myname, self.myname) )
        self.send_privatechat(to, msg, htmlmsg)

    def send_privatechat(self, to, mess, html=None):
        message = domish.Element(('jabber:client','message'))
        message['to'] = to
        message['type'] = "chat"
        message.addElement('body',None, mess)
        if (html is not None):
            message.addRawXml("<html xmlns='http://jabber.org/protocol/xhtml-im'><body xmlns='http://www.w3.org/1999/xhtml'>"+ html +"</body></html>")
        self.xmlstream.send(message)

    def send_groupchat(self, room, mess, html=None):
        message = domish.Element(('jabber:client','message'))
        message['to'] = "%s@conference.%s" %(room, config.get('local','xmppdomain'))
        message['type'] = "groupchat"
        message.addElement('body',None, mess)
        if (html is not None):
            message.addRawXml("<html xmlns='http://jabber.org/protocol/xhtml-im'><body xmlns='http://www.w3.org/1999/xhtml'>"+ html +"</body></html>")
        self.xmlstream.send(message)

    def send_private_request(self, myjid):
        # Got a private message via MUC, send error and then private message
        _handle = myjid.resource
        _room = myjid.user
        if (not ROSTER[_room].has_key(_handle)):
            return
        realjid = ROSTER[_room][_handle]["jid"]

        self.send_help_message( realjid )

        message = domish.Element(('jabber:client','message'))
        message['to'] = myjid.full()
        message['type'] = "chat"
        message.addElement('body',None,"I can't help you here, please chat \
with me outside of a groupchat.  I have initated such a chat for you.")
        self.xmlstream.send(message)

    def processMessagePC(self, elem):
        _from = jid.JID( elem["from"] )
        if (elem["from"] == config.get('local','xmppdomain')):
            print "MESSAGE FROM SERVER?"
            return
        # Intercept private messages via a chatroom, can't do that :)
        if (_from.host == "conference.%s" % (config.get('local','xmppdomain'),)):
            self.send_private_request( _from )
            return

        if (_from.userhost() != "%s_ingest@%s" % (self.handle, config.get('local','xmppdomain'))):
            self.talkWithUser(elem)
            return

        # Go look for body to see routing info! 
        # Get the body string
        bstring = xpath.queryForString('/message/body', elem)
        if not bstring:
            print "Nothing found in body?", bstring
            return
        
        if elem.x and elem.x.hasAttribute("channels"):
            channels = elem.x['channels'].split(",")
        else:
            # The body string contains
            (channel, meat) = bstring.split(":", 1)
            channels = [channel,]
            # Send to chatroom, clip body of channel notation
            #elem.body.children[0] = meat

        # Send to botstalk
        elem['to'] = "botstalk@conference.%s" % (config.get('local','xmppdomain'),)
        elem['type'] = "groupchat"
        self.xmlstream.send( elem )

        # Send to chatroom, clip body
        wfo = channels[0] # TODO
        elem['to'] = "%schat@conference.%s" % (wfo.lower(), 
                                                  config.get('local','xmppdomain'))
        self.xmlstream.send( elem )

        room = "%schat" % (wfo.lower(),)
        if room in CR_WFOS:
            elem['to'] = "crbotstalk@conference.%s" % (config.get('local','xmppdomain'),)
        elif room in SR_WFOS:
            elem['to'] = "srbotstalk@conference.%s" % (config.get('local','xmppdomain'),)
        elif room in ER_WFOS:
            elem['to'] = "erbotstalk@conference.%s" % (config.get('local','xmppdomain'),)
        elif room in WR_WFOS:
            elem['to'] = "wrbotstalk@conference.%s" % (config.get('local','xmppdomain'),)
        elif room in AR_WFOS:
            elem['to'] = "arbotstalk@conference.%s" % (config.get('local','xmppdomain'),)
        elif room in PR_WFOS:
            elem['to'] = "prbotstalk@conference.%s" % (config.get('local','xmppdomain'),)
        else:
            elem['to'] = "unknown@conference.%s" % (config.get('local','xmppdomain'),)
        self.xmlstream.send( elem )

        # Special Routing!
        if ROUTES.has_key( wfo.upper() ):
            for rt in ROUTES[ wfo.upper() ]:
                elem['to'] = "%s@conference.%s" % (rt, config.get('local','xmppdomain'))
                self.xmlstream.send( elem )
