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
        f"Removed {cursor.rowcount} entries from the database "
        f"for screen name '{screen_name}'"
    )
    cursor.close()
    pgconn.commit()

    uri = "http://iembot:9003/reload"
    req = requests.get(uri, timeout=30)
    print(f"reloading iembot {req.text}")


if __name__ == "__main__":
    main(sys.argv)
