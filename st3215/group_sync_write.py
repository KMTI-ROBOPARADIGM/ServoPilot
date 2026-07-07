"""GroupSyncWrite — Batched position write to multiple ST3215 servos.

FILE: st3215/group_sync_write.py
PURPOSE: Builds a sync-write packet containing data for multiple servos and
         sends it in a single transaction. Used for coordinated multi-servo movement.
CALLED BY: ST3215.__init__ creates GroupSyncWrite instance, used in MoveTo/WritePosition
CALLS INTO: protocol_packet_handler.syncWriteTxOnly (protocol_packet_handler.py)
KEY METHODS:
  • addParam(id, data)   — add a servo's data to the batch
  • removeParam(id)      — remove a servo from the batch
  • changeParam(id, data)— update existing servo data
  • clearParam()         — reset the batch
  • txPacket()           — send the assembled sync-write packet
  • makeParam()          — internal: flatten data_dict into param array
"""

from .values import *  # [USER-DEFINED, st3215/values.py] COMM_* constants

class GroupSyncWrite:
    def __init__(self, ph, start_address, data_length):
        self.ph = ph
        self.start_address = start_address
        self.data_length = data_length

        self.is_param_changed = False
        self.param = []
        self.data_dict = {}

        self.clearParam()

    def makeParam(self):
        if not self.data_dict:
            return

        self.param = []

        for sts_id in self.data_dict:
            if not self.data_dict[sts_id]:
                return

            self.param.append(sts_id)
            self.param.extend(self.data_dict[sts_id])

    def addParam(self, sts_id, data):
        if sts_id in self.data_dict:  # sts_id already exist
            return False

        if len(data) > self.data_length:  # input data is longer than set
            return False

        self.data_dict[sts_id] = data

        self.is_param_changed = True
        return True

    def removeParam(self, sts_id):
        if sts_id not in self.data_dict:  # NOT exist
            return

        del self.data_dict[sts_id]

        self.is_param_changed = True

    def changeParam(self, sts_id, data):
        if sts_id not in self.data_dict:  # NOT exist
            return False

        if len(data) > self.data_length:  # input data is longer than set
            return False

        self.data_dict[sts_id] = data

        self.is_param_changed = True
        return True

    def clearParam(self):
        self.data_dict.clear()

    def txPacket(self):
        if len(self.data_dict.keys()) == 0:
            return COMM_NOT_AVAILABLE

        if self.is_param_changed is True or not self.param:
            self.makeParam()

        return self.ph.syncWriteTxOnly(self.start_address, self.data_length, self.param,
                                       len(self.data_dict.keys()) * (1 + self.data_length))
