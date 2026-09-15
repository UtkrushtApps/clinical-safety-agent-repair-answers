import psycopg

from agent.config import Settings


def test_database_is_reachable() -> None:
    with psycopg.connect(Settings.from_env().database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM protocols")
            value = cursor.fetchone()
    assert value is not None
