# See `../backend/` for building `mbs-backend:latest`
FROM mbs-backend:latest
LABEL \
    name="Frontend for the Module Build Service (MBS)" \
    vendor="The Factory 2.0 Team" \
    license="MIT" \
    description="The MBS coordinates module builds. This image is to serve as the MBS frontend." \
    usage="https://pagure.io/fm-orchestrator" \
    build-date=""

RUN dnf -y install \
            httpd \
            mod_wsgi \
    && dnf -y clean all

EXPOSE 8080/tcp 8443/tcp
VOLUME ["/etc/module-build-service", "/etc/fedmsg.d", "/etc/mbs-certs", "/etc/httpd/conf.d"]
ENTRYPOINT ["mod_wsgi-express", "start-server", "/usr/share/mbs/mbs.wsgi"]
CMD [\
    "--user", "fedmsg", "--group", "fedmsg", \
    "--port", "8080", "--threads", "1", \
    "--include-file", "/etc/httpd/conf.d/mbs.conf", \
    "--log-level", "info", \
    "--log-to-terminal", \
    "--access-log", \
    "--startup-log" \
]
