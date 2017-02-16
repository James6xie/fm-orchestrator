import json
import requests

url = 'http://modularity.fedorainfracloud.org:8080/rest_api/v1/unreleasedvariants/'
params = dict(variant_uid='base-runtime-master-3')
print("Querying %r with %r" % (url, params))
response = requests.get(url, params=params)
data = response.json()
entry = data['results'][0]
filename = 'base-runtime-master-3.json'
with open(filename, 'w') as f:
    f.write(json.dumps(entry, indent=2))
print("Wrote %s" % filename)
