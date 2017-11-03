#!/bin/bash -xe

which fedpkg-stage || (echo "sudo dnf install fedpkg-stage" && exit 1)
which jq || (echo "sudo dnf install jq" && exit 1)

FAS=$USER
rm -rf /var/tmp/mbs-test-resume
mkdir /var/tmp/mbs-test-resume
cd /var/tmp/mbs-test-resume

git clone ssh://$FAS@pkgs.stg.fedoraproject.org/rpms/perl-List-Compare
git clone ssh://$FAS@pkgs.stg.fedoraproject.org/modules/testmodule

cd perl-List-Compare
git commit --allow-empty -m "Empty test commit, for MBS in staging."
git push origin master
cd ../testmodule
git commit --allow-empty -m "Empty test commit, for MBS in staging."
git push origin master
build_id=$(fedpkg-stage module-build --optional rebuild_strategy=only-changed | tail -1 | awk '{ print $3 }' | cut -c 2-)
echo "Working with module build $build_id"

echo "Sleeping for 10 seconds before cancelling the build."
sleep 10
fedpkg-stage module-build-cancel $build_id
echo "Build cancellation submitted."

sleep 10
echo "Submitting build again.  Should resume."
fedpkg-stage module-build --optional rebuild_strategy=only-changed -w
echo "HOORAY!  It worked.. I think."
