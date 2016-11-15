#!/bin/bash -e

MBS_HOST=${MBS_HOST:-localhost:5000}

echo "Submitting a build of..."
cat submit-build.json
echo "Using https://$MBS_HOST/module_build_service/module-builds/"
echo "NOTE: You need to be a Fedora packager for this to work"
echo
curl --cert ~/.fedora.cert -k -H "Content-Type: text/json" --data @submit-build.json https://$MBS_HOST/module-build-service/1/module-builds/
echo
