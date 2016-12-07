FROM fedora:24

# so we don't have to compile those when fetched from PyPI
RUN dnf install -y \
        fedmsg-relay \
        gcc \
        git \
        koji \
        krb5-workstation \
        python-devel \
        python-flask \
        python-m2ext \
        python-mock \
        python-pip \
        python2-cffi \
        python2-cryptography \
        python2-pdc-client \
        python2-setuptools \
        python2-zmq \
        redhat-rpm-config \
        rpm-build \
        systemd-devel \
        # Troubleshooting tools
        findutils \
        nc \
        procps \
        telnet \
    && dnf autoremove -y \
    && dnf clean all \
    && mkdir /tmp/module_build_service/
COPY . /tmp/module_build_service/
WORKDIR /tmp/module_build_service/
RUN python setup.py develop
