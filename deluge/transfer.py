# -*- coding: utf-8 -*-
#
# transfer.py
#
# Copyright (C) 2012 Bro <bro.development@gmail.com>
#
# Deluge is free software.
#
# You may redistribute it and/or modify it under the terms of the
# GNU General Public License, as published by the Free Software
# Foundation; either version 3 of the License, or (at your option)
# any later version.
#
# deluge is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with deluge.    If not, write to:
#   The Free Software Foundation, Inc.,
#   51 Franklin Street, Fifth Floor
#   Boston, MA  02110-1301, USA.
#
#    In addition, as a special exception, the copyright holders give
#    permission to link the code of portions of this program with the OpenSSL
#    library.
#    You must obey the GNU General Public License in all respects for all of
#    the code used other than OpenSSL. If you modify file(s) with this
#    exception, you may extend this exception to your version of the file(s),
#    but you are not obligated to do so. If you do not wish to do so, delete
#    this exception statement from your version. If you delete this exception
#    statement from all source files in the program, then also delete it here.
#
#

try:
    import rencode
except ImportError:
    import deluge.rencode as rencode

import zlib
import struct
import logging

from twisted.internet.protocol import Protocol

log = logging.getLogger(__name__)

MESSAGE_HEADER_SIZE = 5

class DelugeTransferProtocol(Protocol):
    """
    Data messages are transfered using very a simple protocol.
    Data messages are transfered with a header containing
    the length of the data to be transfered (payload).

    """
    def __init__(self):
        self._buffer = ""
        self._message_length = 0
        self._bytes_received = 0
        self._bytes_sent = 0

    def transfer_message(self, data):
        """
        Transfer the data.

        The data will be serialized and compressed before being sent.
        First a header is sent - containing the length of the compressed payload
        to come as a signed integer. After the header, the payload is transfered.

        :param data: data to be transfered in a data structure serializable by rencode.

        """
        compressed = zlib.compress(rencode.dumps(data))
        size_data = len(compressed)
        # Store length as a signed integer (using 4 bytes). "!" denotes network byte order.
        payload_len = struct.pack("!i", size_data)
        header = "D" + payload_len
        self._bytes_sent += len(header) + len(compressed)
        self.transport.write(header)
        self.transport.write(compressed)

    def dataReceived(self, data):
        """
        This method is called whenever data is received.

        :param data: a message as transfered by transfer_message, or a part of such
                     a messsage.

        Global variables:
            _buffer         - contains the data received
            _message_length - the length of the payload of the current message.

        """
        self._buffer += data
        self._bytes_received += len(data)

        while len(self._buffer) >= MESSAGE_HEADER_SIZE:
            if self._message_length == 0:
                self._handle_new_message()
            # We have a complete packet
            if len(self._buffer) >= self._message_length:
                self._handle_complete_message(self._buffer[:self._message_length])
                # Remove message data from buffer
                self._buffer = self._buffer[self._message_length:]
                self._message_length = 0
            else:
                break

    def _handle_new_message(self):
        """
        Handle the start of a new message. This method is called only when the
        beginning of the buffer contains data from a new message (i.e. the header).

        """
        try:
            # Read the first bytes of the message (MESSAGE_HEADER_SIZE bytes)
            header = self._buffer[:MESSAGE_HEADER_SIZE]
            payload_len = header[1:MESSAGE_HEADER_SIZE]
            if header[0] != 'D':
                raise Exception("Invalid header format. First byte is %d" % ord(header[0]))
            # Extract the length stored as a signed integer (using 4 bytes)
            self._message_length = struct.unpack("!i", payload_len)[0]
            if self._message_length < 0:
                raise Exception("Message length is negative: %d" % self._message_length)
            # Remove the header from the buffer
            self._buffer = self._buffer[MESSAGE_HEADER_SIZE:]
        except Exception, e:
            log.warn("Error occurred when parsing message header: %s." % str(e))
            log.warn("This version of Deluge cannot communicate with the sender of this data.")
            self._message_length = 0
            self._buffer = ""

    def _handle_complete_message(self, data):
        """
        Handles a complete message as it is transfered on the network.

        :param data: a zlib compressed string encoded with rencode.

        """
        try:
            self.message_received(rencode.loads(zlib.decompress(data), decode_utf8=True))
        except Exception, e:
            log.warn("Failed to decompress (%d bytes) and load serialized data "\
                     "with rencode: %s" % (len(data), str(e)))

    def get_bytes_recv(self):
        """
        Returns the number of bytes received.

        :returns: the number of bytes received
        :rtype: int

        """
        return self._bytes_received

    def get_bytes_sent(self):
        """
        Returns the number of bytes sent.

        :returns: the number of bytes sent
        :rtype: int

        """
        return self._bytes_sent

    def message_received(self, message):
        """Override this method to receive the complete message"""
        pass
