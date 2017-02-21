#!/usr/bin/env python
import socket
import os
import sys
import random

try:
    from urllib.parse import urlencode  # py3
except ImportError:
    from urllib import urlencode  # py2

def listen_for_token():
    """
    Listens on port 13747 on localhost for a redirect request by OIDC
    server, parses the response and returns the "access_token" value.
    """
    TCP_IP = '0.0.0.0'
    TCP_PORT = 13747
    BUFFER_SIZE = 1024

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((TCP_IP, TCP_PORT))
    s.listen(1)

    conn, addr = s.accept()
    print 'Connection address:', addr
    data = ""
    sent_resp = False
    while 1:
        try:
            r = conn.recv(BUFFER_SIZE)
        except:
            conn.close()
            break
        if not r: break
        data += r

        if not sent_resp:
            response = "Token has been handled."
            conn.send("""HTTP/1.1 200 OK
Content-Length: %s
Content-Type: text/plain
Connection: Closed

%s""" % (len(response), response))
            conn.close()
            sent_resp = True

    s.close()

    data = data.split("\n")
    for line in data:
        variables = line.split("&")
        for var in variables:
            kv = var.split("=")
            if not len(kv) == 2:
                continue
            if kv[0] == "access_token":
                return kv[1]
    return None

mbs_host = "localhost:5000"
token = None
if len(sys.argv) > 2:
    token = sys.argv[2]
if len(sys.argv) > 1:
    mbs_host = sys.argv[1]

print "Usage: submit_build.py [mbs_host] [oidc_token]"
print ""
if not token:
    print "Provide token as command line argument or visit following URL to obtain the token:"

    query = urlencode({
        'response_type': 'token',
        'response_mode': 'form_post',
        'nonce': random.randint(100, 10000),
        'scope': ' '.join([
            'openid',
            'https://id.fedoraproject.org/scope/groups',
            'https://mbs.fedoraproject.org/oidc/submit-build',
        ]),
        'client_id': 'mbs-authorizer',
    }) + "&redirect_uri=http://localhost:13747/"
    print "https://id.stg.fedoraproject.org/openidc/Authorization?" + query
    print "We are waiting for you to finish the token generation..."

if not token:
    token = listen_for_token()
if not token:
    print "Failed to get a token from response"
    os._exit(1)

print "Submitting build of ..."
with open("submit-build.json", "r") as build:
    print build.read()
print "Using https://%s/module_build_service/module-builds/" % mbs_host
print "NOTE: You need to be a Fedora packager for this to work"
print

os.system("curl -k -H 'Authorization: Bearer %s' -H 'Content-Type: text/json' --data @submit-build.json https://%s/module-build-service/1/module-builds/ -v" % (token, mbs_host))
