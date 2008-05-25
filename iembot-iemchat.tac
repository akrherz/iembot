# Twisted Bits
from twisted.words.protocols.jabber import client, jid
from twisted.application import service, internet
from twisted.web import server 

# Base Python
import random

# Local Import
import iemchatbot
from secret import *

application = service.Application("The IEMBOT")
serviceCollection = service.IServiceCollection(application)

myJid = jid.JID('iembot@%s/twisted_words' % (CHATSERVER,) )
factory = client.basicClientFactory(myJid, IEMCHAT_PASS)
jabber = iemchatbot.JabberClient(myJid)
factory.addBootstrap('//event/stream/authd',jabber.authd)

i = internet.TCPClient('localhost',5222,factory)
i.setServiceParent(serviceCollection)

xmlrpc = iemchatbot.IEMChatXMLRPC()
xmlrpc.jabber = jabber
x = internet.TCPServer(8002, server.Site(xmlrpc, logPath="web.log"))
x.setServiceParent(serviceCollection)

# END
