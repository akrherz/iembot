
IEMBOT
======

I am a XMPP client with limited bot capabilities.  In general, I am a message
router more than anything.

# pyWWA scripts generate XMPP messages destined to iembot@server
# `iemchatbot.JabberClient` routes these messages into chatrooms
# `iemchatbot.JabberClient` also hands messages off to `publicbot.APPRISSJabberClient`

- I expose a JSON webservice that emits logs of rooms
- I expose a RSS webservice that emits RSS for rooms

the public rooms show up at muc.appriss.com within room names like xxdmxchat,
for Des Moines NWS. 