FROM fedora:28
LABEL \
    name="Backend for the Module Build Service (MBS)" \
    vendor="The Factory 2.0 Team" \
    license="MIT" \
    description="The MBS coordinates module builds. This image is to serve as the MBS backend." \
    usage="https://pagure.io/fm-orchestrator" \
    build-date=""

# The caller can chose to provide an already built module-build-service RPM.
ARG mbs_rpm=module-build-service
ARG mbs_messaging_umb_rpm
ARG umb_ca_crt

RUN dnf -y install \
            python2-pungi \
            python2-psycopg2 \
            https://dl.fedoraproject.org/pub/epel/7Server/x86_64/Packages/s/stomppy-3.1.6-3.el7.noarch.rpm \
            $mbs_rpm \
            $mbs_messaging_umb_rpm \
    && dnf -y clean all

ADD $umb_ca_crt /etc/pki/ca-trust/source/anchors/umb_serverca.crt
# Do this as a workaround instead of `update-ca-trust`
RUN cat /etc/pki/ca-trust/source/anchors/umb_serverca.crt >> /etc/pki/tls/certs/ca-bundle.crt

VOLUME ["/etc/module-build-service", "/etc/fedmsg.d", "/etc/mbs-certs"]
ENTRYPOINT fedmsg-hub
