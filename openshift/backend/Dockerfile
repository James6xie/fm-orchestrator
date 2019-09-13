FROM fedora:29 AS builder

ARG EXTRA_RPMS=""
ARG GIT_REPO=""
ARG GIT_REF=""
ARG VERSION=""
ARG CREATED=""
ARG DNF_CMD="dnf -y --setopt=deltarpm=0 --setopt=install_weak_deps=false --setopt=tsflags=nodocs"

COPY . /src
WORKDIR /src

RUN ${DNF_CMD} install \
      'dnf-command(builddep)' rpm-build rpmdevtools rpmlint \
      python3-tox python3-pytest python3-pytest-cov python3-mock python3-flake8 bandit && \
    ${DNF_CMD} builddep *.spec && \
    ${DNF_CMD} clean all
RUN rpmdev-setuptree && \
    python3 setup.py sdist && \
    rpmbuild --define "_sourcedir $PWD/dist" -ba *.spec && \
    mv $HOME/rpmbuild/RPMS /srv
RUN flake8 && \
    bandit -r -ll -s B102,B303,B411,B602 module_build_service && \
    tox -v -e py3


FROM fedora:29
LABEL \
    org.opencontainers.image.title="Backend for the Module Build Service (MBS)" \
    org.opencontainers.image.description="The MBS coordinates module builds. This image is to serve as the MBS backend." \
    org.opencontainers.image.vendor="The Factory 2.0 Team" \
    org.opencontainers.image.authors="The Factory 2.0 Team <pnt-factory2-devel@redhat.com>" \
    org.opencontainers.image.licenses="MIT" \
    org.opencontainers.image.source="$GIT_REPO" \
    org.opencontainers.image.revision="$GIT_REF" \
    org.opencontainers.image.version="$VERSION" \
    org.opencontainers.image.created="$CREATED" \
    org.opencontainers.image.url="https://pagure.io/fm-orchestrator" \
    org.opencontainers.image.documentation="https://pagure.io/fm-orchestrator" \
    distribution-scope="public"

COPY --from=builder /srv/RPMS /srv/RPMS
COPY repos/ /etc/yum.repos.d/

# TODO: Unpin the `python3-libmodulemd` RPM once MBS is released with libmodulemd v2
RUN $DNF_CMD install \
      python3-psycopg2 \
      python3-docopt \
      python3-service-identity \
      /srv/*/*/*.rpm \
      python3-libmodulemd \
      $EXTRA_RPMS && \
    $DNF_CMD clean all && \
    rm -rf /srv/RPMS

USER 1001

VOLUME ["/etc/module-build-service", "/etc/fedmsg.d", "/etc/mbs-certs"]
CMD ["fedmsg-hub-3"]
