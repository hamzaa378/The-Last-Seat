"""Three independent loops: reliable publisher, AMQP consumer, and recovery sweeper.

Outbox = transactional intent; broker = fast wakeup; due-payment scan = recovery.
An AMQP retry cannot create a second paid ticket because DB status checks are idempotent.
"""
import json
import logging
import threading
import time
from uuid import UUID
import pika
from app.config import RABBITMQ_URL, QUEUE_NAME
from app.database import start_pool, transaction, reader
from app.service import lock_event, reconcile_event, process_payment

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('worker')


def connect_broker():
    conn = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = conn.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    return conn, channel


def publish_outbox():
    while True:
        try:
            broker, channel = connect_broker()
            channel.confirm_delivery()
            log.info('Outbox publisher connected to RabbitMQ')
            while True:
                with transaction() as db:
                    rows = db.execute('''SELECT id,event_type,payload FROM outbox
                                         WHERE published_at IS NULL ORDER BY id
                                         LIMIT 50 FOR UPDATE SKIP LOCKED''').fetchall()
                    for item in rows:
                        channel.basic_publish(exchange='', routing_key=QUEUE_NAME,
                            body=json.dumps({'event_type':item['event_type'],
                                             'payload':item['payload']}).encode(),
                            properties=pika.BasicProperties(delivery_mode=2), mandatory=True)
                        db.execute('UPDATE outbox SET published_at=clock_timestamp() WHERE id=%s',
                                   (item['id'],))
                if not rows:
                    time.sleep(0.5)
        except Exception:
            log.exception('Publisher disconnected; will retry (outbox remains durable)')
            time.sleep(2)
        finally:
            try:
                broker.close()
            except Exception:
                pass


def consume_payments():
    while True:
        try:
            broker, channel = connect_broker()
            channel.basic_qos(prefetch_count=10)
            log.info('Payment consumer connected to RabbitMQ')
            def on_message(ch, method, properties, body):
                try:
                    msg = json.loads(body)
                    if msg['event_type'] == 'PAYMENT_REQUESTED':
                        payment_id = UUID(msg['payload']['payment_id'])
                        with transaction() as db:
                            outcome = process_payment(db, payment_id)
                        log.info('Payment %s: %s', payment_id, outcome)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception:
                    log.exception('Payment handling error; message will be requeued')
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    time.sleep(0.25)
            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message)
            channel.start_consuming()
        except Exception:
            log.exception('Consumer disconnected; will retry')
            time.sleep(2)
        finally:
            try:
                broker.close()
            except Exception:
                pass


def reconciliation_loop():
    while True:
        try:
            # Payment readiness can fall in the future; do not sleep in RabbitMQ callbacks.
            with reader() as db:
                due = db.execute('''SELECT id FROM payment_attempts WHERE status='PENDING'
                                    AND ready_at <= clock_timestamp() ORDER BY ready_at LIMIT 100''').fetchall()
                events = db.execute('SELECT id FROM events ORDER BY id').fetchall()
            for payment in due:
                with transaction() as db:
                    process_payment(db, payment['id'])
            # Short transactions, one event at a time. No global long-lived locks.
            for event in events:
                with transaction() as db:
                    lock_event(db, event['id'])
                    reconcile_event(db, event['id'])
        except Exception:
            log.exception('Reconciliation loop failed; retrying')
        time.sleep(2)


def main():
    start_pool()
    threads = [threading.Thread(target=publish_outbox, daemon=True),
               threading.Thread(target=consume_payments, daemon=True)]
    for thread in threads:
        thread.start()
    log.info('Worker started (AMQP publishing, AMQP consuming, expiry/recovery)')
    reconciliation_loop()


if __name__ == '__main__':
    main()
