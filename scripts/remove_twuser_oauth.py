"""Remove a twitter user's oauth tokens and reload iembot"""

import sys

import requests
from pyiem.database import get_dbconnc


def main(argv):
    """Run for a given username"""
    screen_name = argv[1]
    pgconn, cursor = get_dbconnc("openfire")
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
