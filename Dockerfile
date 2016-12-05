FROM fedora:24

# so we don't have to compile those when fetched from PyPI
RUN dnf install -y \
        python-pip \
        python2-setuptools \
        python2-cffi \
        python2-zmq \
        python2-cryptography \
        koji \
        python2-pdc-client \
        python-m2ext \
        fedmsg-relay \
        python-mock \
        git \
        krb5-workstation \
        systemd-devel \
        gcc \
        redhat-rpm-config \
        python-devel \
        python-flask \
        # Troubleshooting tools
        telnet \
        nc \
        procps \
        findutils \
    && dnf autoremove -y \
    && dnf clean all \
    && mkdir /tmp/module_build_service/
COPY . /tmp/module_build_service/
WORKDIR /tmp/module_build_service/
RUN python setup.py install
