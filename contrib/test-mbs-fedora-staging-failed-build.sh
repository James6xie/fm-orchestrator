#!/bin/bash -xe

which fedpkg-stage || (echo "sudo dnf install fedpkg-stage" && exit 1)
which jq || (echo "sudo dnf install jq" && exit 1)

FAS=$USER
rm -rf /var/tmp/mbs-test-rebuild
mkdir /var/tmp/mbs-test-rebuild
cd /var/tmp/mbs-test-rebuild
git clone ssh://$FAS@pkgs.stg.fedoraproject.org/modules/testmodule
cd testmodule
git checkout fail-mbs-test
git commit --allow-empty -m "Empty test commit, for MBS in staging."
git push origin fail-mbs-test

build_id=$(fedpkg-stage module-build | tail -1 | awk '{ print $3 }' | cut -c 2-)
echo "Working with module build $build_id"
fedpkg-stage module-build-watch $build_id

url=https://mbs.stg.fedoraproject.org/module-build-service/1/module-builds/$build_id
state=$(curl $url | jq '.state')
state_reason=$(curl $url | jq '.state_reason')
if [ "$state" -ne "4" ]; then
    echo "module build state for #$build_id was $state. It should have failed."; exit 1;
fi
if [ "$state_reason" != "\"Some components failed to build.\"" ]; then
    echo "module build state_reason for #$build_id was \"$state_reason\". It should have been \"Some components failed to build.\""; exit 1;
fi
echo "HOORAY!  It worked.. I think."
