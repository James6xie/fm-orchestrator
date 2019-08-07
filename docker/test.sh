#!/bin/bash -ex

mkdir -p ~/mbs
rsync -a --exclude '.*' --exclude '*.pyc' $PWD ~/mbs

cd ~/mbs/src

# We install the python-koji RPM but it doesn't register as installed through pip.
# This hacks keeps tox from install koji from PyPi.
sed -i '/koji/d' requirements.txt

# The python-virtualenv package bundles a very old version of pip,
# which is incompatible with modern virtualenv.
rm -f /usr/lib/python2.7/site-packages/virtualenv_support/pip-9*

# Since tox seems to ignore `usedevelop` when we have `sitepackages` on, we have to run it manually
python setup.py develop --no-deps
/usr/bin/tox -e flake8,py27 "$@"
