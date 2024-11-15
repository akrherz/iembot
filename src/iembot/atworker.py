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


class ATWorkerThead(threading.Thread):
    """The Worker."""

    def __init__(self, queue: Queue, at_handle: str, at_password: str):
        """Constructor."""
        threading.Thread.__init__(self)
        self.queue = queue
        self.at_handle = at_handle
        self.at_password = at_password
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
                print(message)
                print(exp)
                # Invalidate session
                if hasattr(self.client, "session"):
                    delattr(self.client, "session")
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
        if not hasattr(self.client, "session"):
            log.msg(f"Logging in as {self.at_handle}...")
            self.client.login(self.at_handle, self.at_password)

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
            self.at_clients[at_handle] = ATWorkerThead(
                Queue(), at_handle, at_password
            )
            self.at_clients[at_handle].start()

    def submit(self, at_handle: str, message: dict):
        """Submit a message to the client."""
        self.at_clients[at_handle].queue.put(message)
