FROM fedora:24

# so we don't have to compile those when fetched from PyPI
RUN dnf install -y python-pip python2-setuptools python2-cffi python2-zmq python2-cryptography koji python2-pdc-client && \
    dnf autoremove -y && dnf clean all && \
    mkdir /opt/fm-orchestrator/
WORKDIR /opt/fm-orchestrator/
COPY ./requirements.txt /opt/fm-orchestrator/
RUN pip install --user -r ./requirements.txt

COPY koji.conf /etc/rida/

COPY . /opt/fm-orchestrator/

RUN python2 ./manage.py upgradedb && ./generate_localhost_cert.sh
CMD ["python2", "manage.py", "runssl"]
