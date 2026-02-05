"""The ATmosphere Worker.

Need to do some hackery to workaround threadsafety issues with the
atproto module and my general lack of understanding of how to do
threadsafety in Python.  So this is on me.

"""

import threading
from queue import Queue

import httpx
from atproto import Client
from atproto_client.utils import TextBuilder
from twisted.python import log
from twisted.words.xish.domish import Element

from iembot.types import JabberClient
from iembot.util import build_channel_subs


class ATWorkerThread(threading.Thread):
    """The Worker."""

    def __init__(self, queue: Queue, at_handle: str, at_password: str):
        """Constructor."""
        threading.Thread.__init__(self)
        self.queue = queue
        self.at_handle = at_handle
        self.at_password = at_password
        self.logged_in = False
        self.client = Client()
        self.daemon = True  # Don't block on shutdown

    def run(self):
        """Listen for messages from the queue."""
        while True:
            # Grab the message from the queue
            message = self.queue.get()
            if message is None:
                break
            # Process the message
            try:
                self.process_message(message)
            except Exception as exp:
                log.err(exp)
                self.logged_in = False
            self.queue.task_done()

    def process_message(self, msgdict: dict):
        """Process the message."""
        media = msgdict.get("twitter_media")
        img = None
        if media is not None:
            try:
                resp = httpx.get(media, timeout=30)
                resp.raise_for_status()
                img = resp.content
                # AT has a size limit of 976.56KB
                if len(img) > 1_000_000:
                    log.msg(f"{media} is too large({len(img)}) for AT")
                    img = None
            except Exception as exp:
                log.err(exp)

        # Do we need to login?
        if not self.logged_in:
            log.msg(f"Logging in as {self.at_handle}...")
            me = self.client.login(self.at_handle, self.at_password)
            log.msg(repr(me))
            self.logged_in = True

        msg = msgdict["msg"]
        if msg.find("http") > -1:
            parts = msg.split("http")
            msg = TextBuilder().text(parts[0]).link("Link", f"http{parts[1]}")

        if img:
            res = self.client.send_image(
                msg, image=img, image_alt="IEMBot Image TBD"
            )
        else:
            res = self.client.send_post(msg)
        # for now
        log.msg(repr(res))


class ATManager:
    """Ensure the creation of clients and submission of tasks is threadsafe."""

    def __init__(self):
        """Constructor."""
        self.at_clients = {}
        self.lock = threading.Lock()

    def add_client(self, at_handle: str, at_password: str):
        """Add a new client, if necessary."""
        if at_handle in self.at_clients:
            return
        with self.lock:
            self.at_clients[at_handle] = ATWorkerThread(
                Queue(), at_handle, at_password
            )
            self.at_clients[at_handle].start()

    def submit(self, at_handle: str, message: dict):
        """Submit a message to the client."""
        self.at_clients[at_handle].queue.put(message)


def load_atmosphere_from_db(txn, bot: JabberClient):
    """Query database for our config."""

    bot.at_routingtable = build_channel_subs(
        txn,
        "iembot_atmosphere_accounts",
    )

    users = {}
    txn.execute(
        """
    SELECT iembot_account_id, handle, app_pass from
    iembot_atmosphere_accounts
    """
    )
    for row in txn.fetchall():
        user_id = row["iembot_account_id"]
        users[user_id] = {
            "at_handle": row["handle"],
        }
        bot.at_manager.add_client(row["handle"], row["app_pass"])
    bot.at_users = users
    log.msg(f"load_atmosphere_from_db(): {txn.rowcount} accounts found")


def at_send_message(bot: JabberClient, iembot_account_id, msg: str, **kwargs):
    """Send a message to the ATmosphere."""
    at_handle = bot.at_users.get(iembot_account_id, {}).get("at_handle")
    if at_handle is None:
        return
    message = {"msg": msg}
    message.update(kwargs)
    bot.at_manager.submit(at_handle, message)


def route(bot: JabberClient, channels: list, elem: Element):
    """Do the message routing."""
    alerted = []
    for channel in channels:
        for iembot_account_id in bot.at_routingtable.get(channel, []):
            if iembot_account_id in alerted:
                continue
            alerted.append(iembot_account_id)
            # Require the x.twitter attribute to be set to prevent
            # confusion with some ingestors still sending tweets themself
            if not elem.x.hasAttribute("twitter"):
                continue
            lat = long = None
            if (
                elem.x
                and elem.x.hasAttribute("lat")
                and elem.x.hasAttribute("long")
            ):
                lat = elem.x["lat"]
                long = elem.x["long"]
            at_send_message(
                bot,
                iembot_account_id,
                elem.x["twitter"],
                twitter_media=elem.x.getAttribute("twitter_media"),
                latitude=lat,
                longitude=long,
            )
