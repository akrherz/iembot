from twisted.words.xish import domish, xpath
elementStream = domish.elementStream()
roots = []
results = []
elementStream.DocumentStartEvent = roots.append
elementStream.ElementEvent = lambda elem: roots[0].addChild(elem)
elementStream.DocumentEndEvent = lambda: results.append(roots[0])
elementStream.parse("""
<message to="iembot@laptop.local/twisted_words" type="groupchat" from="botstalk@conference.laptop.local/iembot"><body>BMX: BMX issues Area Forecast Discussion (AFD) http://iem.local/p.php?pid=200709121520-KBMX-FXUS62-AFDBMX</body><html xmlns="http://jabber.org/protocol/xhtml-im"><body xmlns="http://www.w3.org/1999/xhtml">BMX issues <a href="http://iem.local/p.php?pid=200709121520-KBMX-FXUS62-AFDBMX">Area Forecast Discussion (AFD)</a> </body></html><x xmlns="nwschat:nwsbot" product_id="200709121520-KBMX-FXUS62-AFDBMX"/><delay xmlns="urn:xmpp:delay" stamp="2013-03-04T22:41:53.524Z" from="botstalk@conference.laptop.local/iembot"/><x xmlns="jabber:x:delay" stamp="20130304T22:41:53" from="botstalk@conference.laptop.local/iembot"/></message>""")

elem = results[0]
items = xpath.queryForNodes("/message/x[@xmlns='jabber:x:delay']", elem)
print items

for item in items:
    print item.toXml()
    print item.getAttribute('affiliation')
