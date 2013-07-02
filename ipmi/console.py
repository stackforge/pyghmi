# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 IBM Corporation
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
# This represents the low layer message framing portion of IPMI

from ipmi.private import session
from ipmi.private import constants

class Console(object):
    """IPMI SOL class.

    This object represents an SOL channel, multiplexing SOL data with
    commands issued by ipmi.command.

    :param bmc: hostname or ip address of BMC
    :param userid: username to use to connect
    :param password: password to connect to the BMC
    :param iohandler: Either a function to call with bytes, a filehandle to
                      use for input and output, or a tuple of (input, output) handles
    :param kg: optional parameter for BMCs configured to require it
    """

    def __init__(self, bmc, userid, password,
                 iohandler=None,
                 force=False, kg=None):
        if type(iohandler) == tuple: #two file handles
            self.console_in = iohandler[0]
            self.console_out = iohandler[1]
        elif type(iohandler) == file: # one full duplex file handle
            self.console_out = iohandler
            self.console_in = iohandler
        elif type(iohander) == types.FunctionType:
            self.console_out = None
            self.out_handler = iohandler
        else:
            raise(Exception('No IO handler provided'))
        self.retriedpayload=0
        self.force_session = force
        self.ipmi_session = session.Session(bmc=bmc,
                                    userid=userid,
                                    password=password,
                                    kg=kg,
                                    onlogon=self._got_session
                                    )

    def _got_session(self, response):
        """Private function to navigate SOL payload activation
        """
        if 'error' in response:
            self.handle.write(response['error'])
            return
        #Send activate sol payload directive
        #netfn= 6 (application)
        #command = 0x48 (activate payload)
        #data = (1, sol payload type
        #        1, first instance
        #        0b11000000, -encrypt, authenticate, disable serial/modem alerts, CTS fine
        #        0, 0, 0 reserved
        self.ipmi_session.raw_command(netfn=0x6, command=0x48, data=(1, 1, 192, 0, 0, 0),
                                      callback=self._payload_activated)

    def _payload_activated(self, response):
        """Check status of activate payload request
        """
        if 'error' in response:
            self.console_out.write(response['error'])
        sol_activate_codes = { #given that these are specific to the command,
                               #it's probably best if one can grep the error and see it
                               #here instead of in constants
            0x81: 'SOL is disabled',
            0x82: 'Maximum SOL session count reached',
            0x83: 'Cannot activate payload with encryption',
            0x84: 'Cannot activate payload without encryption',
            }
        if (response['code']):
            if response['code'] in constants.ipmi_completion_codes:
                self.console_out.write(constants.ipmi_completion_codes[response['code']])
                return
            elif response['code'] == 0x80:
                if self.force_session and not self.retriedpayload:
                    self.retriedpayload=1
                    self.ipmi_session.raw_command(netfn=0x6, command=0x49,
                                                  data=(1, 1, 0, 0, 0, 0),
                                                  callback=self._got_session)
                else:
                    self.console_out.write('SOL Session active for another client\n')
                    return
            elif response['code'] in sol_activate_codes:
                self.console_out.write(sol_activate_codes[response['code']]+'\n')
                return
            else:
                self.console_out.write(
                   'SOL encountered Unrecognized error code %d\n' % response['code'])
                return
        #data[0:3] is reserved except for the test mode, which we don't use
        data = response['data']
        self.maxoutcount = (data[5] << 8) + data[4] 
           #BMC tells us this is the maximum allowed size
        #data[6:7] is the promise of how small packets are going to be, but we don't 
        #have any reason to worry about it
        if (data[8] + (data[9] << 8)) != 623:
            raise Exception("TODO(jbjohnso): support atypical SOL port number")
        #ignore data[10:11] for now, the vlan detail, if used, shouldn't matter to us
        self.ipmi_session.sol_handler=self._got_sol_payload

    def _got_sol_payload(self, payload):
        """SOL payload callback
        """
        self.console_out.write(repr(payload)+'\n')

    def main_loop(self):
        while (1): #TODO(jbjohnso): get out of this loop for exit conditions
            session.Session.wait_for_rsp(timeout=5)