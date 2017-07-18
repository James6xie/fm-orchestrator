import json
import os
import sys

import pdc_client

servername, token = sys.argv[-2], sys.argv[-1]

if os.path.basename(__file__) in (servername, token,):
    raise ValueError("Provide a PDC server name defined in /etc/pdc.d/ and a token")

filename = 'base-runtime-master-3.json'
print("Reading %s" % filename)
with open(filename, 'r') as f:
    entry = json.loads(f.read())

print("Connecting to PDC server %r with token %r" % (servername, token))
pdc = pdc_client.PDCClient(servername, token=token)

print("Submitting POST.")
pdc['unreleasedvariants']._(entry)
print("Done.")
