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
        # Troubleshooting tools
        telnet \
        nc \
    && dnf autoremove -y \
    && dnf clean all \
    && mkdir /opt/module_build_service/ \
    && mkdir /etc/module_build_service
WORKDIR /opt/module_build_service/
COPY ./requirements.txt /opt/module_build_service/
RUN pip install --user -r ./requirements.txt

RUN ln -s /opt/module_build_service/koji.conf /etc/module_build_service/koji.conf \
 && ln -s /opt/module_build_service/copr.conf /etc/module_build_service/copr.conf
