"""Remove a twitter user's oauth tokens and reload iembot"""
from __future__ import print_function

import json
import sys

import psycopg2
import requests


def main(argv):
    """Run for a given username"""
    screen_name = argv[1]
    settings = json.load(open("../settings.json"))
    pgconn = psycopg2.connect(
        database=settings["databaserw"]["openfire"],
        user=settings["databaserw"]["user"],
        host=settings["databaserw"]["host"],
    )
    cursor = pgconn.cursor()
    cursor.execute(
        """
    DELETE from iembot_twitter_oauth where screen_name = %s
    """,
        (screen_name,),
    )
    print(
        ("Removed %s entries from the database for screen name '%s'")
        % (cursor.rowcount, screen_name)
    )
    cursor.close()
    pgconn.commit()

    uri = "http://iembot:9003/reload"
    req = requests.get(uri, timeout=30)
    print("reloading iembot %s" % (repr(req.content),))


if __name__ == "__main__":
    main(sys.argv)
