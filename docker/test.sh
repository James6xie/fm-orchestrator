#!/bin/bash

# We install the python-koji RPM but it doesn't register as installed through pip.
# This hacks keeps tox from install koji from PyPi.
cp requirements.txt requirements.txt.orig
sed -i '/koji/d' requirements.txt
# Delete any leftover compiled Python files
for dir in module_build_service tests; do
    find ${dir} -type f \( -name '*.pyc' -or -name '*.pyc' \) -exec rm -f {} \;
done
# Since tox seems to ignore `usedevelop` when we have `sitepackages` on, we have to run it manually
python setup.py develop --no-deps
/usr/bin/tox -e flake8,py27
rv=$?
# After running tox, we can revert back to the original requirements.txt file
rm -f requirements.txt
mv requirements.txt.orig requirements.txt
exit $rv
