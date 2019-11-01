# See `../backend/` for building `mbs-backend:latest`
FROM mbs-backend:latest

ARG GIT_REPO=""
ARG GIT_REF=""
ARG VERSION=""
ARG CREATED=""
ARG DNF_CMD="dnf -y --setopt=deltarpm=0 --setopt=install_weak_deps=false --setopt=tsflags=nodocs"

LABEL \
    org.opencontainers.image.title="Frontend for the Module Build Service (MBS)" \
    org.opencontainers.image.description="The MBS coordinates module builds. This image is to serve as the MBS frontend." \
    org.opencontainers.image.vendor="The Factory 2.0 Team" \
    org.opencontainers.image.authors="The Factory 2.0 Team <pnt-factory2-devel@redhat.com>" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.source="$GIT_REPO" \
    org.opencontainers.image.revision="$GIT_REF" \
    org.opencontainers.image.version="$VERSION" \
    org.opencontainers.image.created="$CREATED" \
    org.opencontainers.image.url="https://pagure.io/fm-orchestrator" \
    org.opencontainers.image.documentation="https://pagure.io/fm-orchestrator" \
    io.openshift.expose-services="8080:http,8443:https" \
    distribution-scope="public"

USER root

RUN $DNF_CMD install \
      httpd mod_ssl mod_auth_gssapi python3-mod_wsgi && \
    $DNF_CMD clean all

RUN chmod a+rwx /run/httpd && \
    chmod a+rw /etc/passwd && \
    sed -i -r -e 's!Listen 80!Listen 8080!' \
              -e 's!^User apache!User default!' \
              -e 's!^Group apache!Group root!' \
              -e 's!^(\s*CustomLog)\s+\S+!\1 /proc/self/fd/1!' \
              -e 's!^(\s*ErrorLog)\s+\S+!\1 /proc/self/fd/2!' \
        /etc/httpd/conf/httpd.conf && \
    sed -i -r -e 's!Listen 443!Listen 8443!' \
              -e 's!_default_:443!_default_:8443!' \
              -e 's!^(\s*CustomLog)\s+\S+!\1 /proc/self/fd/1!' \
              -e 's!^(\s*TransferLog)\s+\S+!\1 /proc/self/fd/1!' \
              -e 's!^(\s*ErrorLog)\s+\S+!\1 /proc/self/fd/2!' \
              -e 's!^(SSLCertificateFile)\s+\S+!\1 /etc/mbs-certs/frontend.crt!' \
              -e 's!^(SSLCertificateKeyFile)\s+\S+!\1 /etc/mbs-certs/frontend.key!' \
              -e 's!^#(SSLCertificateChainFile)\s+\S+!\1 /etc/mbs-certs/frontendca.crt!' \
        /etc/httpd/conf.d/ssl.conf

COPY openshift/frontend/run /usr/bin

USER 1001

VOLUME ["/etc/module-build-service", "/etc/fedmsg.d", "/etc/mbs-certs", "/etc/httpd/conf.d"]
EXPOSE 8080/tcp 8443/tcp
ENTRYPOINT ["/usr/bin/run"]
CMD ["httpd", "-D", "FOREGROUND"]
