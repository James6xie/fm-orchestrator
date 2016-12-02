Name:		module-build-service
Version:	1.0.0
Release:	1%{?dist}
Summary:	The Module Build Service for Modularity

Group:		Development/Tools
License:	LGPLv2+
URL:		https://pagure.io/fm-orchestrator
# FIXME
Source0:	http://localhost/%{name}-%{version}.tar.gz

BuildArch:	noarch

BuildRequires:	python-setuptools
BuildRequires:	python2-devel

Requires:	fedmsg
Requires:	kobo
Requires:	kobo-rpmlib
Requires:	koji
Requires:	m2crypto
Requires:	mock
Requires:	pdc-client
Requires:	pyOpenSSL
Requires:	python-fedora
Requires:	python-flask
Requires:	python-flask-script
Requires:	python-m2ext
Requires:	python-munch
Requires:	python-six
Requires:	python-sqlalchemy
Requires:	python-systemd
Requires:	python2-flask-migrate
Requires:	python2-flask-sqlalchemy
Requires:	python2-funcsigs
Requires:	python2-mock
Requires:	python2-modulemd
Requires:	python3-mock
Requires:	python3-modulemd


%description
The orchestrator coordinates module builds and is responsible for a number of
tasks:

- Providing an interface for module client-side tooling via which module build
  submission and build state queries are possible.
- Verifying the input data (modulemd, RPM SPEC files and others) is available
  and correct.
- Preparing the build environment in the supported build systems, such as koji.
- Scheduling and building of the module components and tracking the build
  state.
- Emitting bus messages about all state changes so that other infrastructure
  services can pick up the work.


%prep
%setup -q


%build
%py2_build


%install
%py2_install


%files
%doc README.rst
%license LICENSE
%{python2_sitelib}/module_build_service*
%{_bindir}/module_build_service_*
%dir %{_sysconfdir}/module-build-service
%config %{_sysconfdir}/module-build-service/cacert.pem
%config %{_sysconfdir}/module-build-service/config.py
%config %{_sysconfdir}/module-build-service/koji.conf
%config %{_sysconfdir}/module-build-service/copr.conf
%config %{_sysconfdir}/module-build-service/fedmsg.d/logging.py
%config %{_sysconfdir}/module-build-service/fedmsg.d/module_build_service.py
%exclude %{_sysconfdir}/module-build-service/*.py[co]
%exclude %{_sysconfdir}/module-build-service/fedmsg.d/*.py[co]
%exclude %{python2_sitelib}/conf/
%exclude %{python2_sitelib}/tests/


%changelog
* Fri Nov 25 2016 Filip Valder <fvalder@redhat.com> 1.0.0-1
- Let's get this party started.
