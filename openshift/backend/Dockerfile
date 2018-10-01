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

RUN dnf -y install \
            $mbs_rpm \
            $mbs_messaging_umb_rpm \
            python2-psycopg2 \
    && dnf -y clean all

# 1. Use latest stomp.py - hackish way for making this change, until there is
#    sufficient proof that newer versions don't break mbs_messaging_umb
#
# 2. Install python2-docopt - required by the latest version of stomp.py
#
# 3. Install python2-pungi - to make MBS RPMs built for RHEL work with a Fedora
#    base image
RUN sed -i 's/==3\.1\.6//g' /usr/lib/python2.7/site-packages/mbs_messaging_umb-*-py2.7.egg-info/requires.txt \
    && dnf -y install python2-docopt python2-pungi \
    && dnf -y clean all

VOLUME ["/etc/module-build-service", "/etc/fedmsg.d", "/etc/mbs-certs"]
ENTRYPOINT fedmsg-hub
