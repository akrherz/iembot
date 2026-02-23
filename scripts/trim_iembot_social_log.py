"""Remove old data from iembot_social_log"""

from pyiem.database import sql_helper, with_sqlalchemy_conn
from pyiem.util import logger
from sqlalchemy.engine import Connection

LOG = logger()


@with_sqlalchemy_conn("iembot")
def main(conn: Connection | None = None):
    """Run for a given username"""
    res = conn.execute(
        sql_helper(
            "delete from iembot_social_log "
            "where valid < now() - '10 days'::interval"
        )
    )
    LOG.info("Removed %s rows from iembot_social_log", res.rowcount)
    conn.commit()


if __name__ == "__main__":
    main()
