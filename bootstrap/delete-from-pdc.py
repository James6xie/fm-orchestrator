import json
import requests
import os
import sys

import pdc_client

servername, token = sys.argv[-2], sys.argv[-1]

if os.path.basename(__file__) in (servername, token,):
    raise ValueError("Provide a PDC server name defined in /etc/pdc.d/ and a token")

print("Connecting to PDC server %r with token %r" % (servername, token))
pdc = pdc_client.PDCClient(servername, token=token)

print("Submitting DELETE.")
del pdc['unreleasedvariants']['bootstrap']
print("Done.")
