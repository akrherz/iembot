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

__revision__ = '$Id$'


from twisted.words.protocols.jabber import client, jid
from twisted.words.xish import domish, xpath
from twisted.web import xmlrpc, client
from twisted.mail import smtp
from twisted.python import log
from twisted.enterprise import adbapi
from twisted.words.xish.xmlstream import STREAM_END_EVENT
from twisted.internet.task import LoopingCall
from twisted.internet import reactor

import mx.DateTime, socket, re, md5
import StringIO, traceback, base64, urllib
from email.MIMEText import MIMEText

import secret

CHATLOG = {}
ROSTER = {}

CWSU = ['zabchat', 'ztlchat', 'zbwchat', 'zauchat', 'zobchat', 
        'zdvchat', 'zfwchat', 'zhuchat', 'zidchat', 'zkcchat', 
        'zjxchat', 'zlachat', 'zmechat', 'zmachat', 'zmpchat', 
        'znychat', 'zoachat', 'zlcchat', 'zsechat', 'zdcchat']

PRIVATE_ROOMS = ['rgn3fwxchat', 'broemchat', 'wrhchat', 'abqemachat',
                 'jaxemachat', 'bmxalert', 'mlbemchat', 'wxiaweather',
                 'kccichat', 'vipir6and7', 'abc3340', 'dmxemachat',
                 'pspcchat', 'iaseocchat', 'ounemchat','pubemachat',
                 'dvnemachat',
                 'janhydrochat', 'bmxemachat', 'fwdemachat', 'tbwemchat',
                 'tbwnetchat', 'apxfwxchat', 'apxemachat', 'xxxchat',
                 'tbwhamchat', 'lsxemachat', 'spaceflightmet','ekaemachat']

PUBLIC_ROOMS = ['botstalk', 'peopletalk']

WFOS = ['abqchat', 'afcchat', 'afgchat', 'ajkchat', 'akqchat', 'alychat',
        'amachat', 'bgmchat', 'bmxchat', 'boichat', 'bouchat', 'boxchat',
        'brochat', 'btvchat', 'bufchat', 'byzchat', 'caechat', 'carchat',
        'chschat', 'crpchat', 'ctpchat', 'cyschat', 'ekachat', 'epzchat',
        'ewxchat', 'keychat', 'ffcchat', 'fgzchat', 'fwdchat', 'ggwchat',
        'gjtchat', 'gspchat', 'gyxchat', 'hfochat', 'hgxchat', 'hnxchat',
        'hunchat', 'ilmchat', 'janchat', 'jaxchat', 'jklchat', 'lchchat',
        'lixchat', 'lknchat', 'lmkchat', 'loxchat', 'lubchat', 'lwxchat',
        'lzkchat', 'mafchat', 'megchat', 'mflchat', 'mfrchat', 'mhxchat',
        'mlbchat', 'mobchat', 'mrxchat', 'msochat', 'mtrchat', 'ohxchat',
        'okxchat', 'otxchat', 'ounchat', 'pahchat', 'pbzchat', 'pdtchat',
        'phichat', 'pihchat', 'pqrchat', 'psrchat', 'pubchat', 'rahchat',
        'revchat', 'riwchat', 'rlxchat', 'rnkchat', 'sewchat', 'sgxchat',
        'shvchat', 'sjtchat', 'sjuchat', 'slcchat', 'stochat', 'taechat',
        'tbwchat', 'tfxchat', 'tsachat', 'twcchat', 'vefchat', 'abrchat',
        'apxchat', 'arxchat', 'bischat', 'clechat', 'ddcchat', 'dlhchat',
        'dtxchat', 'dvnchat', 'eaxchat', 'fgfchat', 'fsdchat', 'gidchat',
        'gldchat', 'grbchat', 'grrchat', 'ictchat', 'ilnchat', 'ilxchat',
        'indchat', 'iwxchat', 'lbfchat', 'lotchat', 'lsxchat', 'mkxchat',
        'mpxchat', 'mqtchat', 'oaxchat', 'sgfchat', 'topchat', 'unrchat',
        'dmxchat', 'gumchat']

PHONE_RE = re.compile(r'(\d{3})\D*(\d{3})\D*(\d{4})\D*(\d*)')

DBPOOL = adbapi.ConnectionPool("psycopg2",  database="openfire")


class IEMChatXMLRPC(xmlrpc.XMLRPC):

    jabber = None

    def xmlrpc_getAllRoomCount(self):
        r = []
        for rm in ROSTER.keys():
            r.append( [ rm, len(ROSTER[rm]) ] )
        return r

    def xmlrpc_addMUCMember(self, apikey, room, user, affiliation):
        if (apikey != 'apikey'):
            return "apikey did not match, sorry"
        iq = domish.Element((None,'iq'))
        iq['to'] = "%s@conference.%s" %(room.lower(), secret.CHATSERVER)
        iq['type'] = "set"
        iq['id'] = "admin1"
        iq['from'] = self.jabber.myJid.full()
        # Note, this is because openfire supports older NS  JM-391
        iq.addRawXml("<query xmlns='http://jabber.org/protocol/muc#owner'><item affiliation='%s' jid='%s@%s'/></query>" % (affiliation, user, secret.CHATSERVER) )
        self.jabber.xmlstream.send(iq)
        return "OK"

    def xmlrpc_submitSpotternetwork(self, apikey, ts, lon, lat, source, report):
        """ Allow submissions of Spotternet reports """
        if (apikey != secret.snkey):
            return "apikey did not match, sorry"
        if (report is None or len(report) < 10):
            return "report is too short!"
        #jstr = "XXX: ts=%s lon=%s lat=%s source=%s report=%s" % (ts, lon, lat, \
        #    source, report)
        rm = "%schat" % (report[:3].lower(), )
        self.jabber.send_groupchat(rm, report)
        self.jabber.send_groupchat('xxxchat', report)
        self.jabber.send_groupchat('botstalk', report)
        return "THANK YOU"

    def xmlrpc_getUpdate(self, jabberid, xmlkey, room, seqnum):
        """ Return most recent messages since timestamp (ticks...) """
        if (md5.new("%s%s"%(secret.xmlrpc_key, jabberid)).hexdigest() != xmlkey):
            print "Auth error for jabberid: ", jabberid, xmlkey, \
                   md5.new("%s%s"%(secret.xmlrpc_key, jabberid)).hexdigest()
            return
        # If seqnum is zero, we have a new monitor person :)

        #print "XMLRPC-request", room, seqnum, CHATLOG[room]['seqnum']
        r = []
        if (not CHATLOG.has_key(room)):
            return r
        # Optimization
        if (CHATLOG[room]['seqnum'][-1] == seqnum and seqnum > 0):
            return r
        for k in range(len(CHATLOG[room]['seqnum'])):
            if (CHATLOG[room]['seqnum'][k] > seqnum):
                ts = mx.DateTime.DateTimeFromTicks( 
                     CHATLOG[room]['timestamps'][k] / 100.0)
                r.append( [ CHATLOG[room]['seqnum'][k] , 
                            ts.strftime("%Y%m%d%H%M%S"), 
                            CHATLOG[room]['author'][k], 
                            CHATLOG[room]['log'][k] ] )
        #print r
        return r


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
        for rm in CWSU + PRIVATE_ROOMS + PUBLIC_ROOMS + WFOS:
            ROSTER[rm] = {}
            presence = domish.Element(('jabber:client','presence'))
            presence['to'] = "%s@conference.%s/%s" % (rm, secret.CHATSERVER, self.handle)
            reactor.callLater(cnt % 20, self.xmlstream.send, presence)
            cnt += 1

    def daily_timestamp(self):
        """  Send the timestamp into each room, each GMT day... """
        # Make sure we are a bit into the future!
        ts = mx.DateTime.gmt() + mx.DateTime.RelativeDateTime(hours=1)
        mess = "------ %s [GMT] ------" % (ts.strftime("%b %d, %Y"),)
        for rm in CWSU + PRIVATE_ROOMS + PUBLIC_ROOMS + WFOS:
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

        # If the message is x-delay, old message, no relay
        if (x is not None):
            return
        bstring = xpath.queryForString('/message/body', elem)

        # Send a copy of the message to the peopletalk room
        # TODO: support sending the HTML variant
        if (res != self.handle and room in WFOS):
            self.send_groupchat("peopletalk", "[%s] %s: %s"%(room,res,bstring))

        # Look for bot commands
        if (res != self.handle) and re.match(r"^%s:" % (self.handle,), bstring):
            self.process_groupchat_cmd(room, res, bstring[7:].strip())

        # Look for legacy ping
        if (res != self.handle) and re.match(r"^ping", bstring):
            self.process_groupchat_cmd(room, res, "ping")

    def send_group_email(self, room, msgtxt, sender):
        """ Send the chatgroup an email, why don't we """
        # Query for a listing of emails 
        sql = "select distinct email from ofuser u, ofgroupuser g \
               WHERE u.username = g.username and \
               g.groupname = '%sgroup'" % (room.replace("chat","").lower(),)
        DBPOOL.runQuery(sql).addCallback(self.really_send_group_email, room, \
                                         msgtxt, sender)

    def really_send_group_email(self, l, room, msgtxt, sender):
        if not l:
            return
        msg = MIMEText("""The following message has been sent to you from
IEMChat room "%s" by user "%s"
________________________________________________________

%s

________________________________________________________

Please reply to this email if you think you are receiving this in error.

Thank you!""" % (room, sender, msgtxt) )
        msg['subject'] = 'IEMCHAT Message from %s' % (room,)
        msg['From'] = "akrherz@iastate.edu"

        for i in range(len(l)):
            msg['To'] = l[i][0]
            smtp.sendmail("mailhub.iastate.edu", msg['From'], \
                     msg['To'], msg)

        # Always send daryl a copy
        smtp.sendmail("mailhub.iastate.edu", msg['From'], msg['From'], msg)

        err = "Sent email to %s users" % (len(l), )
        self.send_groupchat(room, err)

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
      ,"<a href=\"https://%s/%s.phtml\">Supported Commands</a>" % \
            (secret.CHATSERVER, self.myname) )
            self.send_groupchat(room, err, htmlerr)

    def process_sms(self, room, send_txt, sender):
        # Query for users in chatgroup
        sql = "select i.propvalue as num, i.username as username from \
         nwschat_userprop i, ofgroupuser j WHERE \
         i.username = j.username and \
         j.groupname = '%sgroup'" % (room[:3].lower(),)
        DBPOOL.runQuery(sql).addCallback(self.sendSMS, room, send_txt, sender)

    def sendSMS(self, l, rm, send_txt, sender):
        """ https://mobile.wrh.noaa.gov/mobile_secure/quios_relay.php 
         numbers - string, a comma delimited list of 10 digit
                   phone numbers
         message - string, the message you want to send
        """
        if l:
            numbers = []
            for i in range(len(l)):
                numbers.append( l[i][0] )
                #username = l[i][1]
            str_numbers =  ",".join(numbers)
            self.sms_really_send(rm, str_numbers, sender, send_txt)
        else:
            self.send_groupchat(rm, "No SMS numbers found for chatgroup.")

    def sms_really_send(self, rm, str_numbers, sender, send_txt):
        url = "https://mobile.wrh.noaa.gov/mobile_secure/quios_relay.php"
        basicAuth = base64.encodestring("%s:%s" % (secret.QUIOS_USER, 
                                        secret.QUIOS_PASS) )
        authHeader = "Basic " + basicAuth.strip()
        print 'Sender is', sender
        payload = urllib.urlencode({'numbers': str_numbers,\
                                     'sender': sender,\
                                      'message': send_txt})
        client.getPage(url, postdata=payload, method="POST",\
          headers={"Authorization": authHeader,\
                   "Content-type":"application/x-www-form-urlencoded"}\
          ).addCallback(\
          self.sms_success_gc, rm).addErrback(self.sms_failure_gc, rm)

    def sms_failure_gc(self, res, rm):
        print res
        self.send_groupchat(rm, "SMS Send Failure, Sorry")

    def sms_success_gc(self, res, rm):
        self.send_groupchat(rm, "Sent SMS")

    # Private Chat Variant.....
    def sms_really_send_pc(self, jid, str_numbers, send_txt, resTxt):
        url = "https://mobile.wrh.noaa.gov/mobile_secure/quios_relay.php"
        basicAuth = base64.encodestring("%s:%s" % (secret.QUIOS_USER, 
                                        secret.QUIOS_PASS) )
        authHeader = "Basic " + basicAuth.strip()
        payload = urllib.urlencode({'numbers': str_numbers,\
                                     'sender': self.handle,\
                                      'message': send_txt})
        client.getPage(url, postdata=payload, method="POST",\
          headers={"Authorization": authHeader,\
                   "Content-type":"application/x-www-form-urlencoded"}\
          ).addCallback(\
          self.sms_success_pc, jid, resTxt).addErrback(self.sms_failure_pc, jid)

    def sms_failure_pc(self, res, jid):
        print res
        self.send_privatechat(jid, "SMS Send Confirmation Failure, Sorry")

    def sms_success_pc(self, res, jid, resTxt):
        self.send_privatechat(jid, resTxt)


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
            msg['From'] = "ldm@%s" % (secret.CHATSERVER,)
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

    def confirm_sms(self, elem, bstring):
        print "confirm_sms step1"
        _from = jid.JID( elem["from"] )
        cs = bstring.strip()
        sql = "select * from nwschat_userprop WHERE \
         username = '%s' and name = 'sms_confirm' and propvalue = '%s'"\
         % (_from.user, cs)
        print sql
        DBPOOL.runQuery(sql).addCallback(self.confirm_sms2, elem['from'])

    def confirm_sms2(self, l, jabberid):
        print "confirm_sms2 step2"
        _from = jid.JID( jabberid )
        if not l:
            self.send_privatechat(jabberid, "SMS Confirmation Failed")
            return
        sql = "UPDATE nwschat_userprop SET name = 'sms#' WHERE \
               username = '%s' and name = 'unconfirm_sms#'" % \
              (_from.user,) 
        DBPOOL.runOperation( sql )
        sql = "DELETE from nwschat_userprop WHERE name = 'sms_confirm' and \
               username = '%s'" % \
              (_from.user,) 
        DBPOOL.runOperation( sql )
        self.send_privatechat(jabberid, "SMS Confirmed, thank you!")
   

    def handle_sms_request(self, elem, bstring):
        _from = jid.JID( elem["from"] )
        cmd = bstring.replace("set sms#", "").strip()

        # They can opt out, if they wish
        if (cmd == "0" or cmd == ""):
            sql = "DELETE from nwschat_userprop WHERE username = '%s' and \
               name = 'sms#'" % (_from.user, )
            DBPOOL.runOperation( sql )
            msg = "Thanks, SMS service disabled for your account"
            self.send_privatechat(elem["from"], msg)
            return
        ttt = PHONE_RE.search(cmd)
        if ttt is None:
            self.send_help_message( elem["from"] )
            return
        ar = ttt.groups()
        if len(ar) < 4:
            self.send_help_message( elem["from"] )
            return
        clean_number = "%s%s%s" % (ar[0], ar[1], ar[2])
        clean_number2 = "%s-%s-%s" % (ar[0], ar[1], ar[2])
        sql = "DELETE from nwschat_userprop WHERE username = '%s' and \
           name IN ('sms#', 'unconfirm_sms#', 'sms_confirm')" % (_from.user, )
        DBPOOL.runOperation( sql )
        sql = "INSERT into nwschat_userprop(username, name, propvalue)\
               VALUES ('%s','%s','%s')" % \
               (_from.user, 'unconfirm_sms#', clean_number)
        DBPOOL.runOperation( sql )
        msg = """Thanks, your SMS number is updated to: %s ... We will now send you a confirmation text message to verify this number. Please note: This service is provided without warranty and standard text messaging rates apply.""" % (clean_number2,)
        self.send_privatechat(elem["from"], msg)

        cdnum = "cs%i" % (mx.DateTime.now().second * 1000,)
        pv = "IEMCHAT sms confirmation code is %s" % (cdnum, )
        resTxt = "Sent SMS Confirmation.  Please check your text messages. \
Please respond in this chat with the code number I just sent you."
        self.sms_really_send_pc( elem["from"], clean_number, pv, resTxt)

        sql = "INSERT into nwschat_userprop(username, name, propvalue)\
               VALUES ('%s','%s','%s')" % \
               (_from.user, 'sms_confirm', cdnum)
        DBPOOL.runOperation( sql )


    def send_help_message(self, to):
        msg = """Hi, I am %s.  You can try talking directly with me.
Currently supported commands are:
  set sms# 555-555-5555  (command will set your SMS number)
  set sms# 0             (disables SMS messages from NWSChat)""" % (self.handle,)
        htmlmsg = msg.replace("\n","<br />").replace(self.handle, \
                 "<a href=\"https://%s/%s.phtml\">%s</a>" % \
                 (secret.CHATSERVER, self.myname, self.myname) )
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
        message['to'] = "%s@conference.%s" %(room, secret.CHATSERVER)
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
        if (elem["from"] == secret.CHATSERVER):
            print "MESSAGE FROM SERVER?"
            return
        # Intercept private messages via a chatroom, can't do that :)
        if (_from.host == "conference.%s" % (secret.CHATSERVER,)):
            self.send_private_request( _from )
            return

        if (_from.userhost() != "%s_ingest@%s" % (self.handle, secret.CHATSERVER)):
            self.talkWithUser(elem)
            return

        # Go look for body to see routing info! 
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
        message['to'] = "botstalk@conference.%s" % (secret.CHATSERVER,)
        message['type'] = "groupchat"
        message.addChild( elem.body )
        if (elem.html):
            message.addChild(elem.html)
        self.xmlstream.send(message)

        # Send to chatroom, clip body
        message = domish.Element(('jabber:client','message'))
        message['to'] = "%schat@conference.%s" % (wfo.lower(), secret.CHATSERVER,)
        message['type'] = "groupchat"
        message.addElement('body',None,bstring[4:])
        if (elem.html):
            message.addChild(elem.html)

        self.xmlstream.send(message)
        if (wfo.upper() == "TBW"):
            message['to'] = "%snetchat@conference.%s" % (wfo.lower(), secret.CHATSERVER)
            self.xmlstream.send(message)
            message['to'] = "%shamchat@conference.%s" % (wfo.lower(), secret.CHATSERVER)
            self.xmlstream.send(message)
        if (wfo.upper() == "TBW" or wfo.upper() == "MLB"):
            message['to'] = "%semchat@conference.%s" % (wfo.lower(), secret.CHATSERVER)
            self.xmlstream.send(message)
        if (wfo.upper() == "BMX" or wfo.upper() == "FWD"):
            message['to'] = "%semachat@conference.%s" % (wfo.lower(), secret.CHATSERVER)
            self.xmlstream.send(message)
        if (wfo.upper() == "BMX" or wfo.upper() == "HUN"):
            message['to'] = "abc3340@conference.%s" % ( secret.CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "BMX"):
            message['to'] = "bmxalert@conference.%s" % ( secret.CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "MOB" or wfo.upper() == "TAE" or wfo.upper() == "BMX"):
            message['to'] = "vipir6and7@conference.%s" % ( secret.CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "FFC"):
            message['to'] = "wxiaweather@conference.%s" % ( secret.CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "JAN"):
            message['to'] = "janhydrochat@conference.%s" % ( secret.CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "JAX"):
            message['to'] = "jaxemachat@conference.%s" % (secret.CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "LSX"):
            message['to'] = "lsxemachat@conference.%s" % (secret.CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "ABQ"):
            message['to'] = "abqemachat@conference.%s" % ( secret.CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "OUN"):
            message['to'] = "ounemchat@conference.%s" % ( secret.CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "SLC"):
            message['to'] = "wrhchat@conference.%s" % ( secret.CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "BRO"):
            message['to'] = "broemchat@conference.%s" % ( secret.CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "APX"):
            message['to'] = "apxemachat@conference.%s" % ( secret.CHATSERVER,)
            self.xmlstream.send(message)
            message['to'] = "apxfwxchat@conference.%s" % ( secret.CHATSERVER,)
            self.xmlstream.send(message)
        if (wfo.upper() == "DMX"):
            message['to'] = "%semachat@conference.%s" % (wfo.lower(), secret.CHATSERVER)
            self.xmlstream.send(message)
        if (wfo.upper() == "EKA"):
            message['to'] = "%semachat@conference.%s" % (wfo.lower(), secret.CHATSERVER)
            self.xmlstream.send(message)
        if (wfo.upper() == "PUB"):
            message['to'] = "%semachat@conference.%s" % (wfo.lower(), secret.CHATSERVER)
            self.xmlstream.send(message)
        if (wfo.upper() == "DVN"):
            message['to'] = "%semachat@conference.%s" % (wfo.lower(), secret.CHATSERVER)
            self.xmlstream.send(message)
