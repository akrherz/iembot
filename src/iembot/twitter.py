"""Twitter/X stuff."""

import json
import re
import time
from html import unescape

import requests
from pyiem.reference import TWEET_CHARS
from requests_oauthlib import OAuth1Session
from twisted.internet import threads
from twisted.internet.defer import Deferred
from twisted.python import log
from twisted.words.xish.domish import Element

from iembot.types import JabberClient
from iembot.util import build_channel_subs, email_error

TWEET_API = "https://api.x.com/2/tweets"
# 89: Expired token, so we shall revoke for now
# 185: User is over quota
# 226: Twitter thinks this tweeting user is spammy, le sigh
# 326: User is temporarily locked out
# 64: User is suspended
DISABLE_TWITTER_CODES = [89, 185, 226, 326, 64]


class TwitterRequestError(Exception):
    """Represents a non-2xx response from the X API."""

    def __init__(self, code, payload, status_code):
        super().__init__(f"X API error {code} status {status_code}: {payload}")
        self.code = code
        self.payload = payload
        self.status_code = status_code


def safe_twitter_text(text: str) -> str:
    """Attempt to rip apart a message that is too long!
    To be safe, the URL is counted as 24 chars
    """
    # XMPP payload will have entities, unescape those before tweeting
    text = unescape(text)
    # Convert two or more spaces into one
    text = " ".join(text.split())
    # If we are already below TWEET_CHARS, we don't have any more work to do...
    if len(text) < TWEET_CHARS and text.find("http") == -1:
        return text
    chars = 0
    words = text.split()
    # URLs only count as 25 chars, so implement better accounting
    for word in words:
        if word.startswith("http"):
            chars += 25
        else:
            chars += len(word) + 1
    if chars < TWEET_CHARS:
        return text
    urls = re.findall(r"https?://[^\s]+", text)
    if len(urls) == 1:
        text2 = text.replace(urls[0], "")
        sections = re.findall("(.*) for (.*)( till [0-9A-Z].*)", text2)
        if len(sections) == 1:
            text = f"{sections[0][0]}{sections[0][2]}{urls[0]}"
            if len(text) > TWEET_CHARS:
                sz = TWEET_CHARS - 26 - len(sections[0][2])
                text = f"{sections[0][0][:sz]}{sections[0][2]}{urls[0]}"
            return text
        if len(text) > TWEET_CHARS:
            # 25 for URL, three dots and space for 29
            return f"{text2[: (TWEET_CHARS - 29)]}... {urls[0]}"
    if chars > TWEET_CHARS and words[-1].startswith("http"):
        i = -2
        while len(" ".join(words[:i])) > (TWEET_CHARS - 3 - 25):
            i -= 1
        return f"{' '.join(words[:i])}... {words[-1]}"
    return text[:TWEET_CHARS]


def load_twitter_from_db(txn, bot: JabberClient):
    """Load twitter config from database"""
    bot.tw_routingtable = build_channel_subs(
        txn,
        "iembot_twitter_oauth",
    )

    twusers = {}
    txn.execute(
        """
    SELECT iembot_account_id, access_token, access_token_secret, screen_name,
    iem_owned from
    iembot_twitter_oauth WHERE (iem_owned or (access_token is not null and
    access_token_secret is not null)) and user_id is not null and
    screen_name is not null and not disabled
    """
    )
    for row in txn.fetchall():
        user_id = row["iembot_account_id"]
        twusers[user_id] = {
            "screen_name": row["screen_name"],
            "access_token": row["access_token"],
            "access_token_secret": row["access_token_secret"],
            "iem_owned": row["iem_owned"],
        }
    bot.tw_users = twusers
    log.msg(f"load_twitter_from_db(): {txn.rowcount} oauth tokens found")


def disable_twitter_user(bot: JabberClient, user_id, errcode=0):
    """Disable the twitter subs for this user_id

    Args:
        user_id (big_id): The twitter user to disable
        errcode (int): The twitter errorcode
    """
    twuser = bot.tw_users.get(user_id)
    if twuser is None:
        log.msg(f"Failed to disable unknown twitter user_id {user_id}")
        return False
    screen_name = twuser["screen_name"]
    if twuser["iem_owned"]:
        log.msg(f"Skipping disabling of twitter for {user_id} ({screen_name})")
        return False
    bot.tw_users.pop(user_id, None)
    log.msg(
        f"Removing twitter access token for user: {user_id} ({screen_name}) "
        f"errcode: {errcode}"
    )
    df = bot.dbpool.runOperation(
        "UPDATE iembot_twitter_oauth SET updated = now(), "
        "access_token = null, access_token_secret = null "
        "WHERE user_id = %s",
        (user_id,),
    )
    df.addErrback(log.err)
    return True


def _helper(oauth: OAuth1Session, params):
    """Wrap common stuff"""
    resp = oauth.post(TWEET_API, json=params, timeout=60)
    hh = "x-app-limit-24hour-remaining"
    log.msg(
        f"x-rate-limit-limit {resp.headers.get('x-rate-limit-limit')} + "
        f"{hh} {resp.headers.get(hh)} #{resp.status_code} {resp.text}"
    )
    if resp.status_code >= 300:
        payload = _safe_json(resp)
        errcode = _twitter_error_code_from_payload(payload)
        raise TwitterRequestError(errcode, payload, resp.status_code)
    return _safe_json(resp)


def _upload_media_to_twitter(oauth: OAuth1Session, url: str) -> str | None:
    """Upload Media to Twitter and return its ID"""
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        log.msg(f"Fetching `{url}` got status_code: {resp.status_code}")
        return None
    payload = resp.content
    resp = oauth.post(
        "https://api.x.com/2/media/upload",
        data={"media_category": "tweet_image"},
        files={"media": (url, payload, "image/png")},
    )
    if resp.status_code != 200:
        log.msg(f"X API got status_code: {resp.status_code} {resp.content}")
        return None
    # string required
    jresponse = resp.json()
    media_id = jresponse.get("data", {}).get("id")
    if media_id is None:
        log.msg(f"X API response did not contain id: {jresponse}")
        return None
    return str(media_id)


def twitter_errback(err, bot: JabberClient, user_id, tweettext):
    """Error callback when simple twitter workflow fails."""
    # Always log it
    log.err(err)
    errcode = twittererror_exp_to_code(err)
    if errcode in DISABLE_TWITTER_CODES:
        disable_twitter_user(bot, user_id, errcode)
    else:
        sn = bot.tw_users.get(user_id, {}).get("screen_name", "")
        msg = f"User: {user_id} ({sn})\nFailed to tweet: {tweettext}"
        email_error(err, bot, msg)


def tweet_cb(response, bot: JabberClient, twttxt, _room, myjid, user_id):
    """
    Called after success going to twitter
    """
    log.msg(f"Got {response}")
    if response is None:
        return None
    twuser = bot.tw_users.get(user_id)
    if twuser is None:
        log.msg(f"twuser is None for {user_id}")
        return response
    if "data" not in response:
        log.msg(f"Got response without data {response}")
        return None
    screen_name = twuser["screen_name"]
    url = f"https://x.com/{screen_name}/status/{response['data']['id']}"

    # Log
    df = bot.dbpool.runOperation(
        "INSERT into iembot_social_log(medium, source, resource_uri, "
        "message, response, response_code, iembot_account_id) "
        "values (%s,%s,%s,%s,%s,%s,%s)",
        ("twitter", myjid, url, twttxt, repr(response), 200, user_id),
    )
    df.addErrback(log.err)
    return response


def twittererror_exp_to_code(exp) -> int:
    """Convert a Twitter error exception into a code.

    Args:
      exp (Exception): The exception to convert
    """
    if isinstance(exp, TwitterRequestError):
        return exp.code or 0
    errcode = None
    maybe_failure = getattr(exp, "value", None)
    if isinstance(maybe_failure, TwitterRequestError):
        return maybe_failure.code or 0
    errmsg = str(exp)
    # brittle fallback for older error payloads
    errmsg = errmsg[errmsg.find("[{") : errmsg.find("}]") + 2].replace(
        "'", '"'
    )
    try:
        errobj = json.loads(errmsg)
        errcode = errobj[0].get("code", 0)
    except Exception as exp2:
        log.msg(f"Failed to parse code TwitterError: {exp2}")
    return errcode


def _safe_json(resp: requests.Response) -> dict:
    """Return parsed JSON or a raw text wrapper."""
    try:
        return resp.json()
    except Exception as err:
        log.err(err)
        return {"_raw": resp.text}


def _twitter_error_code_from_payload(payload: dict) -> int:
    """Extract an error code from an X API error payload."""
    if not isinstance(payload, dict):
        log.msg(f"Got non-dict twitter payload? {type(payload)} {payload}")
        return 0
    if "status" in payload:
        return payload["status"]
    errors = payload.get("errors")
    if isinstance(errors, list):
        for err in errors:
            if not isinstance(err, dict):
                continue
            code = err.get("code") or err.get("error_code")
            if isinstance(code, int):
                return code
            if isinstance(code, str) and code.isdigit():
                return int(code)
    return 0


def really_tweet(bot: JabberClient, user_id: int, twttxt: str, **kwargs):
    """Blocking tweet method."""
    oauth = OAuth1Session(
        bot.config["bot.twitter.consumerkey"],
        bot.config["bot.twitter.consumersecret"],
        bot.tw_users[user_id]["access_token"],
        bot.tw_users[user_id]["access_token_secret"],
    )
    log.msg(
        f"Tweeting {bot.tw_users[user_id]['screen_name']}({user_id}) "
        f"'{twttxt}' media:{kwargs.get('twitter_media')}"
    )
    media = kwargs.get("twitter_media")

    params = {
        "text": twttxt,
    }
    # Step 1: Attempt media upload, we may fail, big deal
    try:
        if media is not None:
            media_id = _upload_media_to_twitter(oauth, media)
            if media_id is not None:
                params["media"] = {"media_ids": [media_id]}
    except Exception as err:
        log.msg(f"Uploading media for {media} failed with:")
        log.err(err)

    res = None
    # We now make two attempts to post to Twitter.
    for _ in range(2):
        try:
            res = _helper(oauth, params)
            break
        except TwitterRequestError as exp:
            log.err(exp)
            errcode = exp.code
            if errcode in [185, 187, 403]:
                # 185: Over quota
                # 187: duplicate tweet
                # 403: Forbidden (duplicate)
                return None
            if errcode in DISABLE_TWITTER_CODES:
                disable_twitter_user(bot, user_id, errcode)
                return None

            # Something bad happened with submitting this to twitter
            if str(exp).startswith("media type unrecognized"):
                # The media content hit some error, just send it without it
                log.msg(f"Sending '{kwargs.get('twitter_media')}' fail, strip")
                params.pop("media", None)
            else:
                log.err(exp)
                # Since this called from a thread, sleeping should not jam us
                time.sleep(10)
    return res


def tweet(bot: JabberClient, user_id, twttxt, **kwargs) -> Deferred | None:
    """
    Tweet a message
    """
    df = threads.deferToThread(
        really_tweet,
        bot,
        user_id,
        twttxt,
        **kwargs,
    )
    df.addCallback(tweet_cb, bot, twttxt, "", "", user_id)
    df.addErrback(
        twitter_errback,
        bot,
        user_id,
        twttxt,
    )
    df.addErrback(
        email_error,
        bot,
        f"User: {user_id}, Text: {twttxt} Hit double exception",
    )
    return df


def route(bot: JabberClient, channels: list, elem: Element):
    """Do the twitter work."""
    # Require the x.twitter attribute to be set to prevent
    # confusion with some ingestors still sending tweets themself
    if not elem.x.hasAttribute("twitter"):
        log.msg(f"Failing to tweet message without x {elem.toXml()}")
        return
    msgtxt = safe_twitter_text(elem.x["twitter"])

    lat = long = None
    if elem.x.hasAttribute("lat") and elem.x.hasAttribute("long"):
        lat = elem.x["lat"]
        long = elem.x["long"]

    alerted = []
    for channel in channels:
        for user_id in bot.tw_routingtable.get(channel, []):
            if user_id in alerted:
                continue
            alerted.append(user_id)
            # Ensure we have creds needed for this...
            if user_id not in bot.tw_users:
                log.msg(f"Failed to tweet due to no access_tokens {user_id}")
                continue
            if bot.tw_users[user_id]["access_token"] is None:
                log.msg(f"No twitter access token for {user_id}")
                return None
            tweet(
                bot,
                user_id,
                msgtxt,
                twitter_media=elem.x.getAttribute("twitter_media"),
                latitude=lat,
                longitude=long,
            )
