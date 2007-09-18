# Twisted Bits
from twisted.words.protocols.jabber import client, jid
from twisted.application import service, internet
from twisted.web import server 

# Base Python
import random

# Local Import
import publicbot
from secret import *

application = service.Application("Public IEMBOT")
serviceCollection = service.IServiceCollection(application)


apprissJid = jid.JID('iembot@appriss.com/twisted_%s' % (random.random(),) )
afactory = client.basicClientFactory(apprissJid, APPRISS_PASS)
appriss = publicbot.APPRISSJabberClient(apprissJid)
afactory.addBootstrap('//event/stream/authd',appriss.authd)
afactory.addBootstrap("//event/client/basicauth/invaliduser", appriss.debug)
afactory.addBootstrap("//event/client/basicauth/authfailed", appriss.debug)
afactory.addBootstrap("//event/stream/error", appriss.debug)

a = internet.TCPClient('jabber.appriss.com',5222,afactory)
a.setServiceParent(serviceCollection)

iemJid = jid.JID('iembot2@iemchat.com/twisted_%s' % (random.random(),) )
ifactory = client.basicClientFactory(iemJid, IEMCHAT_PASS)
iembot = publicbot.IEMJabberClient(iemJid)
ifactory.addBootstrap('//event/stream/authd',iembot.authd)
ifactory.addBootstrap("//event/client/basicauth/invaliduser", iembot.debug)
ifactory.addBootstrap("//event/client/basicauth/authfailed", iembot.debug)
ifactory.addBootstrap("//event/stream/error", iembot.debug)

i = internet.TCPClient('iemchat.com',5222,ifactory)
i.setServiceParent(serviceCollection)


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

xmlrpc = publicbot.IEMChatXMLRPC()
x = internet.TCPServer(8003, server.Site(xmlrpc))
x.setServiceParent(serviceCollection)

rss = server.Site( publicbot.RootResource() )
r = internet.TCPServer(8004, rss)
r.setServiceParent(serviceCollection)

# END
