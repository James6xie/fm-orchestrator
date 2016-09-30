#!/bin/sh
echo "Submmiting a build of modules/testmodule, #020ea37251df5019fde9e7899d2f7d7a987dfbf5"
echo "Using https://localhost:5000/rida/module-builds/"
echo "NOTE: You need to be a Fedora packager for this to work"
echo
curl --cert ~/.fedora.cert -k -H "Content-Type: text/json" --data @submit-build.json https://localhost:5000/rida/1/module-builds/
echo
