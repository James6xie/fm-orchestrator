#!/usr/bin/env python3
""" A little script to test submitting a build. """

import requests

response = requests.post('http://127.0.0.1:5000/rida/module-builds/', json={
    'scmurl': 'git://pkgs.stg.fedoraproject.org/modules/core.git',
})

print("%r %s" % (response, response.text))
