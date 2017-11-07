#!/bin/bash -xe

which fedpkg-stage || (echo "sudo dnf install fedpkg-stage" && exit 1)
which jq || (echo "sudo dnf install jq" && exit 1)

FAS=$USER
rm -rf /var/tmp/mbs-test-rebuild
mkdir /var/tmp/mbs-test-rebuild
cd /var/tmp/mbs-test-rebuild

git clone ssh://$FAS@pkgs.stg.fedoraproject.org/rpms/perl-List-Compare
git clone ssh://$FAS@pkgs.stg.fedoraproject.org/modules/testmodule

# First, do a build without changes any components, just to set a baseline.
cd testmodule
git commit --allow-empty -m "Empty test commit, for MBS in staging."
git push origin master
build_id=$(fedpkg-stage module-build --optional rebuild_strategy=only-changed | tail -1 | awk '{ print $3 }' | cut -c 2-)
echo "Working with module build $build_id"
fedpkg-stage module-build-watch $build_id
url=https://mbs.stg.fedoraproject.org/module-build-service/1/module-builds/$build_id
state=$(curl $url | jq '.state')
if [ "$state" -ne "5" ]; then
    echo "initial module build state for #$build_id was $state"; exit 1;
fi
baseline_task_id_1=$(curl $url | jq '.tasks.rpms."perl-List-Compare".task_id')
baseline_task_id_2=$(curl $url | jq '.tasks.rpms."perl-Tangerine".task_id')
baseline_task_id_3=$(curl $url | jq '.tasks.rpms.tangerine.task_id')

# Now that the baseline is established, modify a component and try again.
cd ../perl-List-Compare
git commit --allow-empty -m "Empty test commit, for MBS in staging."
git push origin master
cd ../testmodule
git commit --allow-empty -m "Empty test commit, for MBS in staging."
git push origin master
build_id=$(fedpkg-stage module-build --optional rebuild_strategy=only-changed | tail -1 | awk '{ print $3 }' | cut -c 2-)
echo "Working with module build $build_id"
fedpkg-stage module-build-watch $build_id

url=https://mbs.stg.fedoraproject.org/module-build-service/1/module-builds/$build_id
state=$(curl $url | jq '.state')
if [ "$state" -ne "5" ]; then
    echo "module build state for #$build_id was $state"; exit 1;
fi

actual_task_id_1=$(curl $url | jq '.tasks.rpms."perl-List-Compare".task_id')
actual_task_id_2=$(curl $url | jq '.tasks.rpms."perl-Tangerine".task_id')
actual_task_id_3=$(curl $url | jq '.tasks.rpms.tangerine.task_id')

if [ "$actual_task_id_1" -eq "$baseline_task_id_1" ]; then
    echo "perl-List-Compare task id was the same as before.  It was re-used!  Incorrect."; exit 1;
fi
if [ "$actual_task_id_2" -ne "$baseline_task_id_2" ]; then
    echo "perl-Tangerine task id was NOT the same as before.  It was not reused, but should have been."; exit 1;
fi
if [ "$actual_task_id_3" -ne "$baseline_task_id_3" ]; then
    echo "tangerine task id was NOT the same as before.  It was not reused, but should have been."; exit 1;
fi
echo "HOORAY!  It worked.. I think."
