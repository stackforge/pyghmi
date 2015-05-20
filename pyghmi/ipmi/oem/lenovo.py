# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2015 Lenovo
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pyghmi.constants as pygconst
import pyghmi.ipmi.oem.generic as generic
import pyghmi.ipmi.private.constants as ipmiconst
import pyghmi.ipmi.private.util as util

firmware_types = {
    1: 'Management Controller',
    2: 'UEFI/BIOS',
    3: 'CPLD',
    4: 'Power Supply',
    5: 'Storage Adapter',
    6: 'Add-in Adapter',
}

firmware_event = {
    0: ('Update failed', pygconst.Health.Failed),
    1: ('Update succeeded', pygconst.Health.Ok),
    2: ('Update aborted', pygconst.Health.Ok),
    3: ('Unknown', pygconst.Health.Warning)
}


class OEMHandler(generic.OEMHandler):
    # noinspection PyUnusedLocal
    def __init__(self, oemid, ipmicmd):
        # will need to retain data to differentiate
        # variations.  For example System X versus Thinkserver
        self.oemid = oemid

    def process_event(self, event, ipmicmd, seldata):
        if 'oemdata' in event:
            oemtype = seldata[2]
            oemdata = event['oemdata']
            if oemtype == 0xd0:  # firmware update
                event['component'] = firmware_types.get(oemdata[0], None)
                event['component_type'] = ipmiconst.sensor_type_codes[0x2b]
                slotnumber = (oemdata[1] & 0b11111000) >> 3
                if slotnumber:
                    event['component'] += ' {0}'.format(slotnumber)
                event['event'], severity = firmware_event[oemdata[1] & 0b111]
                event['event_data'] = '{0}.{1}'.format(oemdata[2], oemdata[3])
            elif oemtype == 0xd1:  # BIOS recovery
                event['severity'] = pygconst.Health.Warning
                event['component'] = 'BIOS/UEFI'
                event['component_type'] = ipmiconst.sensor_type_codes[0xf]
                status = oemdata[0]
                method = (status & 0b11110000) >> 4
                status = (status & 0b1111)
                if method == 1:
                    event['event'] = 'Automatic recovery'
                elif method == 2:
                    event['event'] = 'Manual recovery'
                if status == 0:
                    event['event'] += '- Failed'
                    event['severity'] = pygconst.Health.Failed
                if oemdata[1] == 0x1:
                    event['event'] += '- BIOS recovery image not found'
                event['event_data'] = '{0}.{1}'.format(oemdata[2], oemdata[3])
            elif oemtype == 0xd2:  # eMMC status
                if oemdata[0] == 1:
                    event['component'] = 'eMMC'
                    event['component_type'] = ipmiconst.sensor_type_codes[0xc]
                    if oemdata[0] == 1:
                        event['event'] = 'eMMC Format error'
                        event['severity'] = pygconst.Health.Failed
            elif oemtype == 0xd3:
                if oemdata[0] == 1:
                    event['event'] = 'User privilege modification'
                    event['severity'] = pygconst.Health.Ok,
                    event['component'] = 'User Privilege'
                    event['component_type'] = ipmiconst.sensor_type_codes[6]
                    event['event_data'] = \
                        'User {0} on channel {1} from {2} to {3}'.format(
                            oemdata[2], oemdata[1], oemdata[3] & 0b1111,
                            (oemdata[3] & 0b11110000) >> 4
                        )
            else:
                event['event'] = 'OEM event: {0}'.format(
                    ' '.join(format(x, '02x') for x in event['oemdata']))
            return
        evdata = event['event_data_bytes']
        # For HDD bay events, the event data 2 is the bay, modify
        # the description to be more specific
        if (event['event_type_byte'] == 0x6f and
                (evdata[0] & 0b11000000) == 0b10000000 and
                event['component_type_id'] == 13):
            event['component'] += ' {0}'.format(evdata[1] & 0b11111)

    def process_fru(self, fru):
        if fru is None:
            return fru
        if (self.oemid['manufacturer_id'] == 19046 and
                self.oemid['device_id'] == 32):
            fru['oem_parser'] = 'lenovo'
            # Thinkserver lays out specific interpretation of the
            # board extra fields
            _, _, wwn1, wwn2, mac1, mac2 = fru['board_extra']
            if wwn1 not in ('0000000000000000', ''):
                fru['WWN 1'] = wwn1
            if wwn2 not in ('0000000000000000', ''):
                fru['WWN 2'] = wwn2
            if mac1 not in ('00:00:00:00:00:00', ''):
                fru['MAC Address 1'] = mac1
            if mac2 not in ('00:00:00:00:00:00', ''):
                fru['MAC Address 2'] = mac2
            try:
                # The product_extra field is UUID as the system would present
                # in DMI.  This is different than the two UUIDs that
                # it returns for get device and get system uuid...
                byteguid = fru['product_extra'][0]
                # It can present itself as claiming to be ASCII when it
                # is actually raw hex.  As a result it triggers the mechanism
                # to strip \x00 from the end of text strings.  Work around this
                # by padding with \x00 to the right if less than 16 long
                byteguid.extend('\x00' * (16 - len(byteguid)))
                fru['UUID'] = util.decode_wireformat_uuid(byteguid)
            except (AttributeError, KeyError):
                pass
            return fru
        else:
            fru['oem_parser'] = None
            return fru
