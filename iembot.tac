"""Our script that is exec'd from twistd via run.sh"""
# Base Python
import json

# Twisted Bits
from twisted.application import service, internet
from twisted.web import server
from twisted.internet import reactor
from twisted.enterprise import adbapi
from txyam.client import YamClient

# Local Import
from iembot import iemchatbot, webservices

with open('settings.json', encoding="utf-8") as fh:
    dbconfig = json.load(fh)

application = service.Application("Public IEMBOT")
serviceCollection = service.IServiceCollection(application)

# This provides DictCursors!
dbrw = dbconfig.get('databaserw')
dbpool = adbapi.ConnectionPool(
    "pyiem.twistedpg",
    cp_reconnect=True,
    database=dbrw.get('openfire'),
    host=dbrw.get('host'),
    password=dbrw.get('password'),
    user=dbrw.get('user'),
    gssencmode="disable",
)

memcache_client = YamClient(reactor, ['tcp:iem-memcached:11211', ])
memcache_client.connect()

jabber = iemchatbot.JabberClient("iembot", dbpool, memcache_client)

defer = dbpool.runQuery("select propname, propvalue from properties")
defer.addCallback(jabber.fire_client_with_config, serviceCollection)

# 2. JSON channel requests
json = server.Site(webservices.JSONRootResource(jabber), logPath='/dev/null')
x = internet.TCPServer(9003, json)  # pylint: disable=no-member
x.setServiceParent(serviceCollection)

# 3. Answer requests for RSS feeds of the bot logs
rss = server.Site(webservices.RSSRootResource(jabber), logPath="/dev/null")
r = internet.TCPServer(9004, rss)  # pylint: disable=no-member
r.setServiceParent(serviceCollection)

# Increase threadpool size to do more work at once
reactor.getThreadPool().adjustPoolsize(maxthreads=128)
