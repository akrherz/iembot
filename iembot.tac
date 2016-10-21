# Twisted Bits
from twisted.application import service, internet
from twisted.web import server
from twisted.enterprise import adbapi

# Base Python
import json
import os
import sys

# Twisted 16.4 changes import logic
sys.path.insert(0, os.getcwd())

# Local Import
import iemchatbot

dbconfig = json.load(open('settings.json'))

application = service.Application("Public IEMBOT")
serviceCollection = service.IServiceCollection(application)

# This provides DictCursors!
dbrw = dbconfig.get('databaserw')
dbpool = adbapi.ConnectionPool("pyiem.twistedpg", cp_reconnect=True,
                               database=dbrw.get('openfire'),
                               host=dbrw.get('host'),
                               password=dbrw.get('password'),
                               user=dbrw.get('user'))

jabber = iemchatbot.JabberClient("iembot", dbpool)

defer = dbpool.runQuery("select propname, propvalue from properties")
defer.addCallback(jabber.fire_client_with_config, serviceCollection)

# 2. JSON channel requests
json = server.Site(iemchatbot.JSONResource(jabber), logPath='/dev/null')
x = internet.TCPServer(9003, json)
x.setServiceParent(serviceCollection)

# 3. Answer requests for RSS feeds of the bot logs
rss = server.Site(iemchatbot.RootResource(), logPath="/dev/null")
r = internet.TCPServer(9004, rss)
r.setServiceParent(serviceCollection)
