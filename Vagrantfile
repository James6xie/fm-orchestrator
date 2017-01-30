# -*- mode: ruby -*-
# vi: set ft=ruby :

$script = <<SCRIPT
    grep -q '^127\.0\.0\.1 fedmsg-relay$' /etc/hosts || echo "127.0.0.1 fedmsg-relay" >> /etc/hosts
    echo "export KRB5CCNAME=FILE:/var/tmp/krbcc" > /etc/profile.d/module_build_service_developer_env.sh
    echo "export MODULE_BUILD_SERVICE_DEVELOPER_ENV=1" >> /etc/profile.d/module_build_service_developer_env.sh
    source /etc/profile.d/module_build_service_developer_env.sh
    dnf install -y \
        fedmsg-hub \
        fedmsg-relay \
        fedpkg \
        gcc \
        gcc \
        gcc-c++ \
        git \
        koji \
        krb5-workstation \
        libffi-devel \
        openssl-devel \
        python \
        python-devel \
        python-devel \
        python-flask \
        python-mock \
        python-qpid \
        python-virtualenv \
        redhat-rpm-config \
        redhat-rpm-config \
        rpm-build \
        swig \
        systemd-devel
    mkdir /etc/module-build-service/
    cd /tmp/module_build_service
    python setup.py develop
    python setup.py egg_info
    pip install -r test-requirements.txt
SCRIPT

$script_services = <<SCRIPT_SERVICES
    cd /tmp/module_build_service
    mbs-upgradedb > /tmp/mbs-base.out 2>&1
    mbs-gencert >> /tmp/mbs-base.out 2>&1
    fedmsg-relay < /dev/null >& /tmp/fedmsg-relay.out &
    fedmsg-hub < /dev/null >& /tmp/fedmsg-hub.out &
    mbs-frontend < /dev/null >& /tmp/mbs-frontend.out &
SCRIPT_SERVICES

Vagrant.configure("2") do |config|
  config.vm.box = "fedora/24-cloud-base"
  config.vm.synced_folder "./", "/tmp/module_build_service"
  config.vm.provision "file", source: "/var/tmp/krbcc", destination: "/var/tmp/krbcc", run: "always"
  config.vm.network "forwarded_port", guest_ip: "0.0.0.0", guest: 5000, host: 5000
  config.vm.network "forwarded_port", guest_ip: "0.0.0.0", guest: 2001, host: 5001
  config.vm.network "forwarded_port", guest_ip: "0.0.0.0", guest: 13747, host: 13747
  config.vm.provision "shell", inline: $script
  config.vm.provision "shell", inline: $script_services, run: "always"
  config.vm.provider "libvirt" do |domain|
    domain.memory = 1024
    #domain.cpus = 2
  end
  config.vm.provider "virtualbox" do |v|
    v.memory = 1024
    #v.cpus = 2
  end
end
