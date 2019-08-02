#!/bin/bash

# Remove requirements not necessary for Python 3.7.
# Also, prevent koji from being re-installed from PyPi.
cp requirements.txt requirements.txt.orig.py3
sed -i \
    -e '/enum34/d' \
    -e '/funcsigs/d' \
    -e '/futures/d' \
    -e '/koji/d' \
    requirements.txt

# Run everything with Python 3
cp tox.ini tox.ini.orig.py3
sed -i \
    -e 's/py.test/py.test-3/g' \
    -e '/basepython/d' \
    tox.ini

# Delete any leftover compiled Python files
for dir in module_build_service tests; do
    find ${dir} -type f \( -name '*.pyc' -or -name '*.pyc' \) -exec rm -f {} \;
done

# Since tox seems to ignore `usedevelop` when we have `sitepackages` on, we have to run it manually
python3 setup.py develop --no-deps
/usr/bin/tox -e flake8,py3 "$@"
rv=$?

# After running tox, we can revert back to the original files
rm -f requirements.txt tox.ini
mv requirements.txt.orig.py3 requirements.txt
mv tox.ini.orig.py3 tox.ini
exit $rv
