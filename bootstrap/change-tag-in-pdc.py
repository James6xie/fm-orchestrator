import os
import sys

import pdc_client

servername, token, variant_uid, new_tag = \
    sys.argv[-4], sys.argv[-3], sys.argv[-2], sys.argv[-1]

if os.path.basename(__file__) in (servername, token, variant_uid,):
    raise ValueError("Provide a PDC server name defined in "
                     "/etc/pdc.d/ and a token")

print("Connecting to PDC server %r with token %r" % (servername, token))
pdc = pdc_client.PDCClient(servername, token=token)

print("Querying for %r to see what tag it has today" % variant_uid)
obj = pdc['unreleasedvariants'][variant_uid]()
answer = raw_input("Change koji_tag for %r from %r to %r? [y/N]" % (
    variant_uid, obj['koji_tag'], new_tag))
if not answer.lower() in ('y', 'yes'):
    print("Exiting, taking no action.")
    sys.exit(0)

print("Submitting PATCH to new_tag.")
# Do it this way once we fix that ugly PATCH bug.
#pdc['unreleasedvariants'][variant_uid] += {
#    'variant_uid': variant_uid,
#    'koji_tag': new_tag,
#}
try:
    # This way works, but it *always* throws a TypeError.
    pdc['unreleasedvariants/'] += {variant_uid: {'koji_tag': new_tag}}
except TypeError:
    pass

print("Done.")
