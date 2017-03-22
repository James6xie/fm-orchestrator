import os
import sys

import pdc_client

servername, token, variant_uid = sys.argv[-3], sys.argv[-2], sys.argv[-1]

if os.path.basename(__file__) in (servername, token, variant_uid,):
    raise ValueError("Provide a PDC server name defined in /etc/pdc.d/ and a token")

print("Connecting to PDC server %r with token %r" % (servername, token))
pdc = pdc_client.PDCClient(servername, token=token)

print("Querying for %r to see if it is active" % variant_uid)
obj = pdc['unreleasedvariants'][variant_uid]()
assert obj['active'] == True, obj['active']

print("Submitting PATCH to deactivate.")
pdc['unreleasedvariants'][variant_uid] += {'variant_uid': variant_uid, 'active': False}
print("Done.")
