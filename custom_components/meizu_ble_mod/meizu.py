import logging
from binascii import a2b_hex
from datetime import datetime
from threading import Lock

from bluepy.btle import Peripheral

SERVICE_UUID = "000016f2-0000-1000-8000-00805f9b34fb"
_LOGGER = logging.getLogger(__name__)


class MZBtIr(object):

    def __init__(self, mac):
        """
        Initialize a Meizu for the given MAC address.
        """
        self._mac = mac
        self._lock = Lock()
        self._sequence = 0
        self._last_update = None
        self._last_update_battery = None
        self._temperature = None
        self._humidity = None
        self._battery = None
        self._receive_handle = None
        self._receive_buffer = None
        self._received_packet = 0
        self._total_packet = -1

    def get_sequence(self):
        self._sequence += 1
        if self._sequence > 255:
            self._sequence = 0
        return self._sequence

    def mac(self):
        return self._mac

    def temperature(self):
        return self._temperature

    def humidity(self):
        return self._humidity

    def battery(self):
        if self.voltage() is None:
            return None

        v = self.voltage()
        b = int((v - 2.3) / 0.7 * 100)
        if b < 0:
            b = 0
        return b

    def voltage(self):
        return self._battery

    def update(self, update_battery=True):
        self._lock.acquire()
        p = None
        try:
            p = Peripheral(self._mac, "public")
            ch_list = p.getCharacteristics()
            for ch in ch_list:
                if str(ch.uuid) == SERVICE_UUID:
                    if p.writeCharacteristic(ch.getHandle(), b'\x55\x03' + bytes([self.get_sequence()]) + b'\x11',
                                             True):
                        data = ch.read()
                        humihex = data[6:8]
                        temphex = data[4:6]
                        temp10 = int.from_bytes(temphex, byteorder='little')
                        humi10 = int.from_bytes(humihex, byteorder='little')
                        self._temperature = float(temp10) / 100.0
                        self._humidity = float(humi10) / 100.0
                        if update_battery:
                            if p.writeCharacteristic(ch.getHandle(),
                                                     b'\x55\x03' + bytes([self.get_sequence()]) + b'\x10', True):
                                data = ch.read()
                                battery10 = data[4]
                                self._battery = float(battery10) / 10.0
                                self._last_update_battery = datetime.now()
                    break
        except Exception as ex:
            _LOGGER.debug("Unexpected error: {}", ex)
        finally:
            if p is not None:
                p.disconnect()
            self._lock.release()

    def send_ir_raw(self, data):
        ir = data.strip()
        arr = ir.split(':', 1)
        return self.send_ir(arr[0], arr[1])

    def send_ir(self, key, ir_data):
        self._lock.acquire()
        sent = False
        p = None
        try:
            p = Peripheral(self._mac, "public")
            ch_list = p.getCharacteristics()
            for ch in ch_list:
                if str(ch.uuid) == SERVICE_UUID:
                    sequence = self.get_sequence()
                    if p.writeCharacteristic(ch.getHandle(),
                                             b'\x55' + bytes([len(a2b_hex(key)) + 3, sequence]) + b'\x03' + a2b_hex(
                                                 key), True):
                        data = ch.read()
                        if len(data) == 5 and data[4] == 1:
                            sent = True
                        else:
                            send_list = []
                            packet_count = int(len(ir_data) / 30) + 1
                            if len(data) % 30 != 0:
                                packet_count += 1
                            send_list.append(b'\x55' + bytes([len(a2b_hex(key)) + 5, sequence]) + b'\x00' + bytes(
                                [0, packet_count]) + a2b_hex(key))
                            i = 0
                            while i < packet_count - 1:
                                if len(ir_data) - i * 30 < 30:
                                    send_ir_data = ir_data[i * 30:]
                                else:
                                    send_ir_data = ir_data[i * 30:(i + 1) * 30]
                                send_list.append(
                                    b'\x55' + bytes([int(len(send_ir_data) / 2 + 4), sequence]) + b'\x00' + bytes(
                                        [i + 1]) + a2b_hex(send_ir_data))
                                i += 1
                            error = False
                            for j in range(len(send_list)):
                                r = p.writeCharacteristic(ch.getHandle(), send_list[j], True)
                                if not r:
                                    error = True
                                    break
                            if not error:
                                sent = True
                    break
        except Exception as ex:
            _LOGGER.debug("Unexpected error: {}", ex)
        finally:
            if p is not None:
                p.disconnect()
            self._lock.release()
        return sent

    def receive_ir(self, timeout=15):
        self._lock.acquire()
        self._receive_handle = None
        self._receive_buffer = False
        self._received_packet = 0
        self._total_packet = -1
        try:
            p = Peripheral(self._mac, "public")
            chList = p.getCharacteristics()
            for ch in chList:
                if str(ch.uuid) == SERVICE_UUID:
                    self._receive_handle = ch.getHandle()
                    sequence = self.get_sequence()
                    if p.writeCharacteristic(ch.getHandle(), b'\x55\x03' + bytes([sequence]) + b'\x05', True):
                        data = ch.read()
                        if len(data) == 4 and data[3] == 7:
                            p.withDelegate(self)
                            while self._received_packet != self._total_packet:
                                if not p.waitForNotifications(timeout):
                                    self._receive_buffer = False
                                    break
                            p.writeCharacteristic(ch.getHandle(), b'\x55\x03' + bytes([sequence]) + b'\x0b', True)
                            p.writeCharacteristic(ch.getHandle(), b'\x55\x03' + bytes([sequence]) + b'\x06', True)
                        else:
                            self._receive_buffer = False
                    break
            self._receive_handle = None
            p.disconnect()
        except Exception as ex:
            print("Unexpected error: {}".format(ex))
            self._receive_handle = None
            self._receive_buffer = False
            p.disconnect()
        finally:
            self._lock.release()
        return self._receive_buffer

    def handle_notification(self, cHandle, data):
        if cHandle == self._receive_handle:
            if len(data) > 4 and data[3] == 9:
                if data[4] == 0:
                    self._total_packet = data[5]
                    self._receive_buffer = []
                    self._received_packet += 1
                elif data[4] == self._received_packet:
                    self._receive_buffer.extend(data[5:])
                    self._received_packet += 1
                else:
                    self._receive_buffer = False
                    self._total_packet = -1
