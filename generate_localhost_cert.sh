#!/bin/bash

openssl req -subj '/CN=localhost/O=My Company Name LTD./C=US' -new -newkey rsa:2048 -days 365 -nodes -x509 -keyout server.key -out server.crt
