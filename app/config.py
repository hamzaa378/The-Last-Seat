import os

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://tickets:tickets@localhost:5432/tickets')
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
RABBITMQ_URL = os.getenv('RABBITMQ_URL', 'amqp://guest:guest@localhost:5672/')
JWT_SECRET = os.getenv('JWT_SECRET', 'LOCAL_DEVELOPMENT_ONLY_CHANGE_ME')
HOLD_SECONDS = int(os.getenv('HOLD_SECONDS', '120'))
CACHE_SECONDS = int(os.getenv('CACHE_SECONDS', '2'))
PAYMENT_DELAY_SECONDS = int(os.getenv('PAYMENT_DELAY_SECONDS', '10'))
QUEUE_NAME = 'payments.requested'
