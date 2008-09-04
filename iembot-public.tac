# Twisted Bits
from twisted.words.protocols.jabber import client, jid
from twisted.application import service, internet
from twisted.web import server 

# Base Python
import random

# Local Import
import publicbot
import secret

application = service.Application("Public IEMBOT")
serviceCollection = service.IServiceCollection(application)


apprissJid = jid.JID('iembot@%s/twisted_%s' % (secret.APPRISS,random.random()))
afactory = client.basicClientFactory(apprissJid, secret.APPRISS_PASS)
appriss = publicbot.APPRISSJabberClient(apprissJid)
afactory.addBootstrap('//event/stream/authd',appriss.authd)
afactory.addBootstrap("//event/client/basicauth/invaliduser", appriss.debug)
afactory.addBootstrap("//event/client/basicauth/authfailed", appriss.debug)
afactory.addBootstrap("//event/stream/error", appriss.debug)

a = internet.TCPClient(secret.APPRISS_SRV,5222,afactory)
a.setServiceParent(serviceCollection)


iemJid = jid.JID('iembot2@%s/twisted_%s' % (secret.CHATSERVER, random.random()))
ifactory = client.basicClientFactory(iemJid, secret.IEMCHAT_PASS)
iembot = publicbot.IEMJabberClient(iemJid)
iembot.addAppriss( appriss )
ifactory.addBootstrap('//event/stream/authd',iembot.authd)
ifactory.addBootstrap("//event/client/basicauth/invaliduser", iembot.debug)
ifactory.addBootstrap("//event/client/basicauth/authfailed", iembot.debug)
ifactory.addBootstrap("//event/stream/error", iembot.debug)

i = internet.TCPClient(secret.CHATSERVER,5222,ifactory)
i.setServiceParent(serviceCollection)


xmlrpc = publicbot.IEMChatXMLRPC()
x = internet.TCPServer(8003, server.Site(xmlrpc, logPath="xmlrpc.log"))
x.setServiceParent(serviceCollection)

rss = server.Site( publicbot.RootResource(), logPath="rss.log" )
r = internet.TCPServer(8004, rss)
r.setServiceParent(serviceCollection)

# END
