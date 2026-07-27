import json
import logging
import os
from threading import Lock
from django.apps import AppConfig
from django.conf import settings
from confluent_kafka import Producer

logger = logging.getLogger(__name__)

class WhatsappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lead.whatsapp"

    def ready(self):
        """
        App initialization lifecycle hook. 
        Kafka producer instantiation is omitted here to prevent multi-process fork corruption.
        """
        logger.info("WhatsApp high-concurrency layer configured.")


class KafkaProducerClient:
    """
    Production-grade, thread-safe, lazily initialized Kafka Producer Client.
    Engineered with explicit optimizations for high-throughput scaling (100k+ concurrent leads).
    """
    _producer = None
    _lock = Lock()

    @classmethod
    def _get_producer(cls) -> Producer:
        """
        Thread-safe Double-Checked Locking singleton pattern ensuring 
        exactly one Kafka Producer exists per worker process memory space.
        """
        if cls._producer is None:
            with cls._lock:
                if cls._producer is None:
                    # Dynamically draw configuration from Django settings with local fail-safes
                    bootstrap_servers = getattr(
                        settings, 
                        "KAFKA_BOOTSTRAP_SERVERS", 
                        os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
                    )
                    
                    # Production Engine Performance Configuration Matrix
                    kafka_config = {
                        "bootstrap.servers": bootstrap_servers,
                        "client.id": "whatsapp-livechat-producer",
                        
                        # High-Throughput & Scale Tunings
                        "acks": "all",                      # Guarantees no data loss across broker clusters
                        "compression.type": "snappy",       # Fast CPU-efficient compression for chat texts
                        "linger.ms": 20,                    # Batches messages over 20ms windows to maximize IOPS efficiency
                        "queue.buffering.max.messages": 150000, # Comfortably absorbs 100k+ lead spikes
                        
                        # Network Resilience Parameters
                        "retries": 5,                       # Automatically handles transient network dropouts
                        "retry.backoff.ms": 150,            # Mitigates thundering herd syndrome during broker rebalances
                    }
                    
                    logger.info("Spinning up thread-isolated confluent-kafka producer context...")
                    cls._producer = Producer(kafka_config)
                    
        return cls._producer

    @classmethod
    def _delivery_report(cls, err, msg):
        """
        Asynchronous, non-blocking response frame execution handler.
        Fires automatically when the Kafka cluster acknowledges or rejects the record payload.
        """
        if err is not None:
            logger.error(f"Kafka engine record drop! Critical failure: {err}")
        else:
            logger.debug(
                f"Payload acknowledged: partition [{msg.partition()}] "
                f"at offset {msg.offset()}"
            )

    @classmethod
    def publish_event(cls, topic: str, key: str, value: dict):
        """
        Pushes structural JSON frames onto the memory queue topology asynchronously.
        
        Args:
            topic: Destination Kafka topic name (e.g., 'whatsapp_outbound_messages')
            key: Partitioning key (e.g., chat_id). Guarantees sequential message execution order per chat thread.
            value: Data dictionary containing the payload context.
        """
        try:
            producer = cls._get_producer()
            
            # Strict serialization handling
            serialized_value = json.dumps(value).encode("utf-8")
            serialized_key = str(key).encode("utf-8") if key else None

            # Enqueue execution event to the threadpool non-blockingly
            producer.produce(
                topic=topic,
                key=serialized_key,
                value=serialized_value,
                callback=cls._delivery_report
            )
            
            # Serves delivery callbacks instantaneously from the queue matrix
            producer.poll(0)
            
        except BufferError:
            # Mitigation fallback if the memory queue fills up under massive load spikes
            logger.warning("Kafka buffer allocation exhausted. Executing emergency synchronous drain...")
            cls.flush(timeout=1.0)
            
            # Retry message injection into reclaimed memory space
            producer.produce(
                topic=topic, 
                key=serialized_key, 
                value=serialized_value, 
                callback=cls._delivery_report
            )
        except Exception as e:
            logger.error(f"Failed to publish event framework to topic {topic}: {str(e)}")
            raise

    @classmethod
    def flush(cls, timeout: float = 2.0):
        """
        Blocks execution context until all outstanding queue entries are completed.
        Call during graceful worker thread termination lifecycles.
        """
        if cls._producer:
            cls._producer.flush(timeout)

