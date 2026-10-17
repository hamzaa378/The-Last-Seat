"""One small, bounded pool per process; an explicit SQL transaction per mutation."""
from contextlib import contextmanager
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from app.config import DATABASE_URL

pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=12, open=False,
                      kwargs={'autocommit': True, 'row_factory': dict_row})


def start_pool():
    pool.open()
    pool.wait(timeout=30)


def stop_pool():
    pool.close()


@contextmanager
def transaction():
    with pool.connection() as conn:
        with conn.transaction():
            yield conn


@contextmanager
def reader():
    with pool.connection() as conn:
        yield conn
