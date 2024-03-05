"""Our script that is exec'd from twistd via run.sh"""

# Base Python
import json

# Local Import
from iembot import iemchatbot, webservices
from psycopg.rows import dict_row

# Twisted Bits
from twisted.application import internet, service
from twisted.enterprise import adbapi
from twisted.internet import reactor
from twisted.web import server
from txyam.client import YamClient

with open("settings.json", encoding="utf-8") as fh:
    dbconfig = json.load(fh)

application = service.Application("Public IEMBOT")
serviceCollection = service.IServiceCollection(application)

# This provides DictCursors!
dbrw = dbconfig.get("databaserw")
dbpool = adbapi.ConnectionPool(
    "psycopg",
    cp_reconnect=True,
    dbname=dbrw.get("openfire"),
    host=dbrw.get("host"),
    password=dbrw.get("password"),
    user=dbrw.get("user"),
    gssencmode="disable",
    row_factory=dict_row,
)

memcache_client = YamClient(
    reactor,
    [
        "tcp:iem-memcached:11211",
    ],
)
memcache_client.connect()

jabber = iemchatbot.JabberClient("iembot", dbpool, memcache_client)

defer = dbpool.runQuery("select propname, propvalue from properties")
defer.addCallback(jabber.fire_client_with_config, serviceCollection)

# 2. JSON channel requests
json = server.Site(webservices.JSONRootResource(jabber), logPath="/dev/null")
x = internet.TCPServer(9003, json)  # pylint: disable=no-member
x.setServiceParent(serviceCollection)

# 3. Answer requests for RSS feeds of the bot logs
rss = server.Site(webservices.RSSRootResource(jabber), logPath="/dev/null")
r = internet.TCPServer(9004, rss)  # pylint: disable=no-member
r.setServiceParent(serviceCollection)

# Increase threadpool size to do more work at once
# 128 not large enough when SPC's products come through :/
reactor.getThreadPool().adjustPoolsize(maxthreads=256)
