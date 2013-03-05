import ConfigParser
config = ConfigParser.ConfigParser()
config.read('config.ini')

# Twisted Bits
from twisted.words.protocols.jabber import client, jid
from twisted.application import service, internet
from twisted.web import server 

# Base Python
import datetime

# Local Import
import publicbot
import iemchatbot

now = datetime.datetime.now()

application = service.Application("Public IEMBOT")
serviceCollection = service.IServiceCollection(application)

# 1.  Bot logs into Appriss for relaying stuff....
apprissJid = jid.JID('%s@%s/twisted_%s' % (config.get('appriss','user'),
	config.get('appriss','xmppdomain'), now.strftime("%Y%m%d%H%M")))
appriss = publicbot.APPRISSJabberClient(apprissJid)

afactory = client.basicClientFactory(apprissJid, 
									config.get('appriss','password'))
afactory.addBootstrap('//event/stream/authd',appriss.authd)
afactory.addBootstrap("//event/client/basicauth/invaliduser", appriss.debug)
afactory.addBootstrap("//event/client/basicauth/authfailed", appriss.debug)
afactory.addBootstrap("//event/stream/error", appriss.debug)
a = internet.TCPClient( config.get("appriss", "connecthost"), 5222, afactory)
a.setServiceParent(serviceCollection)

# 2. Bot logs into main server for routing
myJid = jid.JID('iembot@%s/twisted_words' % (config.get('local', 'xmppdomain'),) )
# Configure the IEMBot with a reference to the appriss bot
jabber = iemchatbot.JabberClient(myJid, appriss)
jabber.compute_daily_caller() # Setup daily spamming of rooms
factory = client.basicClientFactory(myJid, config.get('local', 'password'))
factory.addBootstrap('//event/stream/authd',jabber.authd)
b = internet.TCPClient(config.get('local', 'connecthost'), 5222, factory)
b.setServiceParent(serviceCollection)

# 3. JSON channel requests
json = server.Site( iemchatbot.JSONResource(jabber), logPath='/dev/null' )
x = internet.TCPServer(8003, json)
x.setServiceParent(serviceCollection)

# 4. Answer requests for RSS feeds of the bot logs
rss = server.Site( iemchatbot.RootResource(), logPath="/dev/null" )
r = internet.TCPServer(8004, rss)
r.setServiceParent(serviceCollection)

# END
