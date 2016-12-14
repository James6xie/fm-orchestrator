Name:		module-build-service
Version:	1.0.1
Release:	1%{?dist}
Summary:	The Module Build Service for Modularity

Group:		Development/Tools
License:	MIT
URL:		https://pagure.io/fm-orchestrator
Source0:	https://files.pythonhosted.org/packages/source/m/%{name}/%{name}-%{version}.tar.gz

BuildArch:	noarch

BuildRequires:	python-setuptools
BuildRequires:	python2-devel

BuildRequires:	systemd
%{?systemd_requires}

Requires:	systemd
Requires:	fedmsg
Requires:	git
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
Requires:	python-httplib2
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
Requires:	rpm-build


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

mkdir -p %{buildroot}%{_unitdir}/
%{__install} -pm644 conf/mbs-scheduler.service \
    %{buildroot}%{_unitdir}/mbs-scheduler.service

%post
%systemd_post mbs-scheduler.service

%preun
%systemd_preun mbs-scheduler.service

%postun
%systemd_postun_with_restart mbs-scheduler.service

%files
%doc README.rst
%license LICENSE
%{python2_sitelib}/module_build_service*
%{_bindir}/mbs-*
%{_unitdir}/mbs-scheduler.service
%dir %{_sysconfdir}/module-build-service
%config(noreplace) %{_sysconfdir}/module-build-service/config.py
%config(noreplace) %{_sysconfdir}/module-build-service/koji.conf
%config(noreplace) %{_sysconfdir}/module-build-service/copr.conf
%config(noreplace) %{_sysconfdir}/fedmsg.d/mbs-logging.py
%config(noreplace) %{_sysconfdir}/fedmsg.d/module_build_service.py
%exclude %{_sysconfdir}/module-build-service/cacert.pem
%exclude %{_sysconfdir}/module-build-service/*.py[co]
%exclude %{_sysconfdir}/fedmsg.d/*.py[co]
%exclude %{python2_sitelib}/conf/
%exclude %{python2_sitelib}/tests/


%changelog
* Mon Dec 12 2016 Ralph Bean <rbean@redhat.com> - 1.0.1-1
- Cleanup in preparation for package review.

* Tue Dec 6 2016 Matt Prahl <mprahl@redhat.com> - 1.0.0-2
- Adds systemd unit.

* Fri Nov 25 2016 Filip Valder <fvalder@redhat.com> - 1.0.0-1
- Let's get this party started.
