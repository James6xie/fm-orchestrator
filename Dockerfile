FROM fedora:24

# so we don't have to compile those when fetched from PyPI
RUN dnf install -y python-pip python2-setuptools python2-cffi python2-zmq python2-cryptography koji python2-pdc-client python-m2ext fedmsg-relay && \
    dnf autoremove -y && dnf clean all && \
    mkdir /opt/module_build_service/
WORKDIR /opt/module_build_service/
COPY ./requirements.txt /opt/module_build_service/
RUN pip install --user -r ./requirements.txt

COPY koji.conf /etc/module_build_service/
COPY copr.conf /etc/module_build_service/

COPY . /opt/module_build_service/

RUN python2 ./manage.py upgradedb && python2 manage.py generatelocalhostcert