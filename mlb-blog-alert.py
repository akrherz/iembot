# Check MLB's blog for updates!

import urllib2, mx.DateTime
import elementtree.ElementTree as ET
from twisted.words.xish import domish
import logging, secret
from twisted.words.protocols.jabber import client, jid, xmlstream
from twisted.words.xish import domish
from twisted.internet import reactor



class JabberClient:
    xmlstream = None

    def __init__(self, myJid):
        self.myJid = myJid


    def authd(self,xmlstream):
        logging.info("Logged into Jabber Chat Server!")
        self.xmlstream = xmlstream
        presence = domish.Element(('jabber:client','presence'))
        xmlstream.send(presence)

        xmlstream.addObserver('/message',  self.debug)
        xmlstream.addObserver('/presence', self.debug)
        xmlstream.addObserver('/iq',       self.debug)

    def sendMessage(self, body, html=None):
        while (self.xmlstream is None):
            logging.info("xmlstream is None, so lets try again!")
            reactor.callLater(3, self.sendMessage, body, html)
            return
        message = domish.Element(('jabber:client','message'))
        message['to'] = 'iembot@iemchat.com'
        message['type'] = 'chat'

        # message.addElement('subject',None,subject)
        message.addElement('body',None,body)
        if (html is not None):
            message.addRawXml("<html xmlns='http://jabber.org/protocol/xhtml-im'><body xmlns='http://www.w3.org/1999/xhtml'>"+ html +"</body></html>")
        self.debug( message )
        self.xmlstream.send(message)


    def debug(self, elem):
        logging.info( elem.toXml().encode('utf-8') )
        logging.info("="*20 )


def writeTS(ts):
  o = open('mlbts.txt', 'w')
  o.write( ts.strftime("%Y%m%d%H%M%S") )
  o.close()

def stopme():
  reactor.stop()

def doit():
  # Load old timestamp
  o = open('mlbts.txt').read()
  oldts = mx.DateTime.strptime(o[:14], "%Y%m%d%H%M%S")
  logts = oldts

  # Download RSS
  req = urllib2.Request("http://www.srh.noaa.gov/mlb/IMUblog/rss.xml")
  xml = urllib2.urlopen(req).read()

  # Check timestamps
  tree = ET.fromstring(xml)

  a = tree.findall('.//item')
  for elem in a:
    title = elem.findtext('title')
    ts = elem.findtext('pubDate')
    #Wed, 05 Sep 2007 23:27:20 -0400
    post_ts = mx.DateTime.strptime( ts[5:25], "%d %b %Y %H:%M:%S")
    if (post_ts > oldts):
      # Fire alert!
      txt = "MLB: Impact Weather Blog updated ("+title+") http://www.srh.noaa.gov/mlb/IMUblog/blog.html"
      html = "<a href=\"http://www.srh.noaa.gov/mlb/IMUblog/blog.html\">Impact Weather Blog</a> updated ("+title+")"
      jabber.sendMessage(txt,html)
  
      if (post_ts > logts):
        writeTS(post_ts)
        logts = post_ts

  stopme()


myJid = jid.JID('nwsbot_ingest@nwschat.weather.gov/ingest_%s' % ( mx.DateTime.gmt().ticks(), ) )
factory = client.basicClientFactory(myJid, secret.IEMCHAT_PASS)

jabber = JabberClient(myJid)

factory.addBootstrap('//event/stream/authd',jabber.authd)
factory.addBootstrap("//event/client/basicauth/invaliduser", jabber.debug)
factory.addBootstrap("//event/client/basicauth/authfailed", jabber.debug)
factory.addBootstrap("//event/stream/error", jabber.debug)

reactor.connectTCP('nwschat.weather.gov',5222,factory)

reactor.callLater(10, doit)
reactor.callLater(240, stopme)
reactor.run()
