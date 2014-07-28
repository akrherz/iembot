# Twisted Bits
from twisted.application import service, internet
from twisted.web import server 
from twisted.enterprise import adbapi

# Base Python
import json

# Local Import
import iemchatbot

dbconfig = json.load(open('settings.json'))

application = service.Application("Public IEMBOT")
serviceCollection = service.IServiceCollection(application)

# This provides DictCursors!
dbpool = adbapi.ConnectionPool("pyiem.twistedpg", cp_reconnect=True,
                            database=dbconfig.get('databaserw').get('openfire'),
                            host=dbconfig.get('databaserw').get('host'),
                            password=dbconfig.get('databaserw').get('password'),
                            user=dbconfig.get('databaserw').get('user') )

jabber = iemchatbot.JabberClient(dbpool)

defer = dbpool.runQuery("select propname, propvalue from properties")
defer.addCallback(jabber.fire_client_with_config, serviceCollection)

# 2. JSON channel requests
json = server.Site( iemchatbot.JSONResource(jabber), logPath='/dev/null' )
x = internet.TCPServer(8003, json)
x.setServiceParent(serviceCollection)

# 3. Answer requests for RSS feeds of the bot logs
rss = server.Site( iemchatbot.RootResource(), logPath="/dev/null" )
r = internet.TCPServer(8004, rss)
r.setServiceParent(serviceCollection)

# END
