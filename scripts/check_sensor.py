#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Open and release the default sensor without enrolling or deleting prints."""
import gi
from gi.repository import Gio, GLib


def main():
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    def call(path, interface, method, args=None):
        return bus.call_sync('net.reactivated.Fprint', path, interface, method, args,
                             None, Gio.DBusCallFlags.NONE, 20000, None)
    path = call('/net/reactivated/Fprint/Manager', 'net.reactivated.Fprint.Manager',
                'GetDefaultDevice').unpack()[0]
    interface = 'net.reactivated.Fprint.Device'
    call(path, interface, 'Claim', GLib.Variant('(s)', ('',)))
    try:
        print('Sensor opened successfully.')
    finally:
        call(path, interface, 'Release')
        print('Sensor released.')


if __name__ == '__main__':
    main()
