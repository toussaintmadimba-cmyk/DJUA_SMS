from __future__ import annotations

from collections import deque

from djua_sms_gateway.gsm.models import CmtiNotification, ModemSms


class ScriptedTransport:
    def __init__(self, script=None, *, spontaneous=None, initially_open=True):
        self.is_open = initially_open
        self.commands = []
        self.open_calls = 0
        self.close_calls = 0
        self.reconnect_calls = 0
        self.reset_calls = 0
        self._pending = deque()
        self._spontaneous = deque(spontaneous or [])
        self._script = {}
        for command, value in (script or {}).items():
            if value and isinstance(value[0], (list, tuple)):
                groups = [list(group) for group in value]
            else:
                groups = [list(value)]
            self._script[command] = deque(groups)

    def open(self):
        self.open_calls += 1
        self.is_open = True

    def close(self):
        self.close_calls += 1
        self.is_open = False

    def reconnect(self):
        self.reconnect_calls += 1
        self.is_open = True

    def write_line(self, line):
        if not self.is_open:
            raise IOError("closed")
        self.commands.append(line)
        groups = self._script.get(line)
        response = groups.popleft() if groups and groups else ["ERROR"]
        self._pending.extend(response)

    def read_line(self):
        if not self.is_open:
            raise IOError("closed")
        if self._pending:
            item = self._pending.popleft()
            if isinstance(item, Exception):
                raise item
            return item
        if self._spontaneous:
            item = self._spontaneous.popleft()
            if isinstance(item, Exception):
                raise item
            return item
        return None

    def reset_buffers(self):
        self.reset_calls += 1
        self._pending.clear()


class FakeSerialDevice:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.is_open = True
        self.writes = []
        self.reads = deque()
        self.flushed = 0
        self.reset_in = 0
        self.reset_out = 0
        self.fail_write = False
        self.fail_read = False

    def write(self, data):
        if self.fail_write:
            raise OSError("write failed")
        self.writes.append(data)
        return len(data)

    def flush(self):
        self.flushed += 1

    def readline(self):
        if self.fail_read:
            raise OSError("read failed")
        return self.reads.popleft() if self.reads else b""

    def reset_input_buffer(self):
        self.reset_in += 1

    def reset_output_buffer(self):
        self.reset_out += 1

    def close(self):
        self.is_open = False


class FakeModem:
    def __init__(self, sms=None, notifications=None):
        self.sms = {
            (item.storage, item.index): item for item in (sms or [])
        }
        self.notifications = deque(notifications or [])
        self.deleted = []
        self.delete_error = None
        self.read_error = None
        self.list_error = None

    def read_sms(self, storage, index):
        if self.read_error:
            raise self.read_error
        return self.sms[(storage, index)]

    def delete_sms(self, storage, index):
        if self.delete_error:
            raise self.delete_error
        self.deleted.append((storage, index))

    def list_all_sms(self):
        if self.list_error:
            raise self.list_error
        return list(self.sms.values())

    def poll_notification(self, *, timeout_seconds=0.0):
        return self.notifications.popleft() if self.notifications else None


def modem_sms(body, *, storage="SM", index=1, sender="+243810000001", timestamp="26/09/28,06:00:00+04"):
    return ModemSms(
        storage=storage,
        index=index,
        status="REC UNREAD",
        sender=sender,
        modem_timestamp=timestamp,
        raw_body=body,
    )


def cmti(index=1, storage="SM"):
    return CmtiNotification(storage=storage, index=index)
