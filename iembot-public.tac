# Twisted Bits
from twisted.words.protocols.jabber import client, jid
from twisted.application import service, internet
from twisted.web import server 
from twisted.internet import reactor

# Base Python
import random

# Local Import
import publicbot
import iemchatbot
import secret
import mx.DateTime

application = service.Application("Public IEMBOT")
serviceCollection = service.IServiceCollection(application)

# 1.  Bot logs into Appriss for relaying stuff....
apprissJid = jid.JID('iembot@%s/twisted_%s' % (secret.APPRISS,random.random()))
afactory = client.basicClientFactory(apprissJid, secret.APPRISS_PASS)
appriss = publicbot.APPRISSJabberClient(apprissJid)
afactory.addBootstrap('//event/stream/authd',appriss.authd)
afactory.addBootstrap("//event/client/basicauth/invaliduser", appriss.debug)
afactory.addBootstrap("//event/client/basicauth/authfailed", appriss.debug)
afactory.addBootstrap("//event/stream/error", appriss.debug)
a = internet.TCPClient(secret.APPRISS_SRV,5222,afactory)
a.setServiceParent(serviceCollection)


# 2. Bot logs into main server for syndication
iemJid = jid.JID('iembot2@%s/twisted_%s' % (secret.CHATSERVER, random.random()))
ifactory = client.basicClientFactory(iemJid, secret.IEMCHAT_PASS)
iembot = publicbot.IEMJabberClient(iemJid)
iembot.addAppriss( appriss )
ifactory.addBootstrap('//event/stream/authd',iembot.authd)
ifactory.addBootstrap("//event/client/basicauth/invaliduser", iembot.debug)
ifactory.addBootstrap("//event/client/basicauth/authfailed", iembot.debug)
ifactory.addBootstrap("//event/stream/error", iembot.debug)
i = internet.TCPClient('localhost',5222,ifactory)
i.setServiceParent(serviceCollection)

#3. Bot logs into main server for routing
myJid = jid.JID('iembot@%s/twisted_words' % (secret.CHATSERVER,) )
factory = client.basicClientFactory(myJid, secret.IEMCHAT_PASS)
jabber = iemchatbot.JabberClient(myJid)
factory.addBootstrap('//event/stream/authd',jabber.authd)
# Setup daily caller
tnext =  mx.DateTime.gmt() + mx.DateTime.RelativeDateTime(hour=0,
                              days=1,minute=0,second=0)
print 'Initial Calling daily_timestamp in %s seconds' % \
       ((tnext - mx.DateTime.gmt()).seconds, )
reactor.callLater((tnext - mx.DateTime.gmt()).seconds, jabber.daily_timestamp)
i2 = internet.TCPClient('localhost',5222,factory)
i2.setServiceParent(serviceCollection)


# 4. Answer xmlrpc requests for room updates
#xmlrpc = publicbot.IEMChatXMLRPC()
#x = internet.TCPServer(8003, server.Site(xmlrpc, logPath="xmlrpc.log"))
#x.setServiceParent(serviceCollection)

# 4. JSON channel requests
#    iembot-http/channel/dmx/12341234234
json = server.Site( publicbot.JsonChannel(), logPath='web.log' )
x = internet.TCPServer(8003, json)
x.setServiceParent(serviceCollection)

# 5. Answer requests for RSS feeds of the bot logs
rss = server.Site( publicbot.RootResource(), logPath="rss.log" )
r = internet.TCPServer(8004, rss)
r.setServiceParent(serviceCollection)

# END
