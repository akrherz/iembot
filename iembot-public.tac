import ConfigParser
config = ConfigParser.ConfigParser()
config.read('config.ini')


# Twisted Bits
from twisted.words.protocols.jabber import client, jid
from twisted.application import service, internet
from twisted.web import server 
from twisted.internet import reactor

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
	
afactory = client.basicClientFactory(apprissJid, config.get('appriss','password'))
appriss = publicbot.APPRISSJabberClient(apprissJid)
afactory.addBootstrap('//event/stream/authd',appriss.authd)
afactory.addBootstrap("//event/client/basicauth/invaliduser", appriss.debug)
afactory.addBootstrap("//event/client/basicauth/authfailed", appriss.debug)
afactory.addBootstrap("//event/stream/error", appriss.debug)
a = internet.TCPClient( config.get("appriss", "connecthost"),5222,afactory)
a.setServiceParent(serviceCollection)


# 2. Bot logs into main server for syndication
iemJid = jid.JID('iembot2@%s/twisted_%s' % (config.get('local', 'xmppdomain'), 
	now.strftime("%Y%m%d%H%M")))
ifactory = client.basicClientFactory(iemJid, config.get('local', 'password'))
iembot = publicbot.IEMJabberClient(iemJid)
iembot.addAppriss( appriss )
ifactory.addBootstrap('//event/stream/authd',iembot.authd)
ifactory.addBootstrap("//event/client/basicauth/invaliduser", iembot.debug)
ifactory.addBootstrap("//event/client/basicauth/authfailed", iembot.debug)
ifactory.addBootstrap("//event/stream/error", iembot.debug)
i = internet.TCPClient(config.get('local', 'connecthost'),5222,ifactory)
i.setServiceParent(serviceCollection)

#3. Bot logs into main server for routing
myJid = jid.JID('iembot@%s/twisted_words' % (config.get('local', 'xmppdomain'),) )
factory = client.basicClientFactory(myJid, config.get('local', 'password'))
jabber = iemchatbot.JabberClient(myJid)
factory.addBootstrap('//event/stream/authd',jabber.authd)
# Setup daily caller
utc = datetime.datetime.utcnow() + datetime.timedelta(days=1)
tnext =  utc.replace(hour=0,minute=0,second=0)
print 'Initial Calling daily_timestamp in %s seconds' % (
	(tnext - datetime.datetime.utcnow()).seconds, )
reactor.callLater((tnext - datetime.datetime.utcnow()).seconds, jabber.daily_timestamp)
i2 = internet.TCPClient(config.get('local', 'connecthost'),5222,factory)
i2.setServiceParent(serviceCollection)

# 4. JSON channel requests
json = server.Site( publicbot.JsonChannel(), logPath='/dev/null' )
x = internet.TCPServer(8003, json)
x.setServiceParent(serviceCollection)

# 5. Answer requests for RSS feeds of the bot logs
rss = server.Site( publicbot.RootResource(), logPath="/dev/null" )
r = internet.TCPServer(8004, rss)
r.setServiceParent(serviceCollection)

# END
