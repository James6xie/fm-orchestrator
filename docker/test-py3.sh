#!/bin/bash -ex

mkdir -p ~/mbs
rsync -a --exclude '.*' --exclude '*.pyc' $PWD ~/mbs

cd ~/mbs/src

# Remove requirements not necessary for Python 3.7.
# Also, prevent koji from being re-installed from PyPi.
sed -i \
    -e '/enum34/d' \
    -e '/funcsigs/d' \
    -e '/futures/d' \
    -e '/koji/d' \
    requirements.txt

# Run everything with Python 3
sed -i \
    -e 's/py.test/py.test-3/g' \
    -e '/basepython/d' \
    tox.ini

# Since tox seems to ignore `usedevelop` when we have `sitepackages` on, we have to run it manually
python3 setup.py develop --no-deps
/usr/bin/tox -e flake8,py3,intflake "$@"
