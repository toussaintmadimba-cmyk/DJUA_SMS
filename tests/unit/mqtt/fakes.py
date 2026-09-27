from djua_sms_gateway.mqtt.client import PublishReceipt
from djua_sms_gateway.storage.models import InboundStatus, OutboxStatus
from djua_sms_gateway.storage.repository import utc_now


class FakeTransport:
    def __init__(self, *, connected=True, connect_error=None, mids=None, auto_ack=False):
        self._connected = connected
        self.connect_error = connect_error
        self.mids = iter(mids or range(1, 1000))
        self.auto_ack = auto_ack
        self.ack_handler = None
        self.disconnect_handler = None
        self.calls = []
        self.connect_calls = 0
        self.disconnect_calls = 0

    @property
    def connected(self):
        return self._connected

    def set_publish_ack_handler(self, handler):
        self.ack_handler = handler

    def set_disconnect_handler(self, handler):
        self.disconnect_handler = handler

    def connect(self):
        self.connect_calls += 1
        if self.connect_error:
            raise self.connect_error
        self._connected = True

    def reconnect(self):
        self.connect()

    def disconnect(self):
        self.disconnect_calls += 1
        self._connected = False

    def publish(self, topic, payload, *, qos, retain):
        if not self._connected:
            raise RuntimeError("offline")
        mid = next(self.mids)
        self.calls.append((mid, topic, payload, qos, retain))
        if self.auto_ack and self.ack_handler:
            self.ack_handler(mid)
        return PublishReceipt(mid)

    def ack(self, mid):
        if self.ack_handler:
            self.ack_handler(mid)

    def drop(self):
        self._connected = False
        if self.disconnect_handler:
            self.disconnect_handler()


class FakePahoInfo:
    def __init__(self, mid, rc=0):
        self.mid = mid
        self.rc = rc


class FakePahoClient:
    def __init__(
        self,
        *,
        connect_reason=0,
        connect_fail=False,
        publish_rc=0,
        auto_ack=False,
    ):
        self.connect_reason = connect_reason
        self.connect_fail = connect_fail
        self.publish_rc = publish_rc
        self.auto_ack = auto_ack
        self.on_connect = None
        self.on_connect_fail = None
        self.on_disconnect = None
        self.on_publish = None
        self.username = None
        self.password = None
        self.tls = False
        self.delay = None
        self.loop_started = False
        self.calls = []
        self.mid = 0

    def username_pw_set(self, username, password):
        self.username = username
        self.password = password

    def tls_set(self):
        self.tls = True

    def reconnect_delay_set(self, **kwargs):
        self.delay = kwargs

    def connect_async(self, host, port, keepalive):
        self.calls.append(("connect_async", host, port, keepalive))
        return 0

    def loop_start(self):
        self.loop_started = True
        if self.connect_fail:
            self.on_connect_fail(self, None)
        else:
            self.on_connect(self, None, None, self.connect_reason, None)

    def reconnect(self):
        if self.connect_fail:
            self.on_connect_fail(self, None)
        else:
            self.on_connect(self, None, None, self.connect_reason, None)
        return 0

    def loop_stop(self):
        self.loop_started = False

    def disconnect(self):
        if self.on_disconnect:
            self.on_disconnect(self, None, None, 0, None)
        return 0

    def publish(self, topic, payload, qos, retain):
        self.mid += 1
        mid = self.mid
        self.calls.append(("publish", topic, payload, qos, retain, mid))
        if self.auto_ack and self.on_publish:
            self.on_publish(self, None, mid, 0, None)
        return FakePahoInfo(mid, self.publish_rc)


def seed_outbox(
    repository,
    *,
    key="1",
    topic=None,
    payload='{"x":1}',
    qos=1,
    retain=False,
):
    now = utc_now()
    topic = topic or f"djua/test/DJUA-KIN-00000{key}/telemetry"
    with repository.database.transaction(immediate=True) as connection:
        cursor = connection.execute(
            """
            INSERT INTO inbound_sms (
                sender, gateway_received_at, raw_body, raw_dedupe_key,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"+243{key}",
                now,
                f"raw-{key}",
                f"raw-key-{key}",
                InboundStatus.QUEUED.value,
                now,
                now,
            ),
        )
        sms_id = cursor.lastrowid
        cursor = connection.execute(
            """
            INSERT INTO mqtt_outbox (
                sms_id, topic, payload_json, qos, retain, status,
                attempt_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                sms_id,
                topic,
                payload,
                qos,
                int(retain),
                OutboxStatus.PENDING.value,
                now,
                now,
            ),
        )
        outbox_id = cursor.lastrowid
    return repository.get_outbox(outbox_id)
