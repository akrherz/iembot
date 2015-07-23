
IEMBOT
======

[![Docs](https://readthedocs.org/projects/iembot/badge/?version=latest)](https://readthedocs.org/projects/iembot/)

[![Build Status](https://travis-ci.org/akrherz/iembot.svg)](https://travis-ci.org/akrherz/iembot)

[![Coverage Status](https://coveralls.io/repos/akrherz/iembot/badge.svg?branch=master&service=github)](https://coveralls.io/github/akrherz/iembot?branch=master)

[![Code Health](https://landscape.io/github/akrherz/iembot/master/landscape.svg?style=flat)](https://landscape.io/github/akrherz/iembot/master)

I am a XMPP client with limited bot capabilities.  In general, I am a message
router more than anything.

# pyWWA scripts generate XMPP messages destined to iembot@server
# `iemchatbot.JabberClient` routes these messages into chatrooms
# `iemchatbot.JabberClient` also hands messages off to `publicbot.APPRISSJabberClient`

- I expose a JSON webservice that emits logs of rooms
- I expose a RSS webservice that emits RSS for rooms

the public rooms show up at conference.weather.im within room names like dmxchat,
for Des Moines NWS. 
