import json
import requests
import os
import sys
import yaml

import pdc_client

filename = 'bootstrap-master-1.json'
print("Reading %s" % filename)
with open(filename, 'r') as f:
    entry = json.loads(f.read())

print entry['modulemd']
modulemd = yaml.load(entry['modulemd'])
mbs = {}
mbs['commit'] = modulemd['data']['xmd']['mbs_commit']
mbs['buildrequires'] = modulemd['data']['xmd']['mbs_buildrequires']
del modulemd['data']['xmd']['mbs_commit']
del modulemd['data']['xmd']['mbs_buildrequires']
modulemd['data']['xmd']['mbs'] = mbs
entry['modulemd'] = yaml.dump(modulemd)

filename = "fixed-" + filename
print("Writing %s" % filename)
with open(filename, 'w') as f:
    entry = f.write(json.dumps(entry, indent=2))
