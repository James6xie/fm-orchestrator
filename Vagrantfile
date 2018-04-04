# -*- mode: ruby -*-
# vi: set ft=ruby :

$script = <<SCRIPT
    grep -q '^127\.0\.0\.1 fedmsg-relay$' /etc/hosts || echo "127.0.0.1 fedmsg-relay" >> /etc/hosts
    echo "export MODULE_BUILD_SERVICE_DEVELOPER_ENV=1" > /etc/profile.d/module_build_service_developer_env.sh
    source /etc/profile.d/module_build_service_developer_env.sh
    dnf install -y \
        fedmsg-hub \
        fedmsg-relay \
        fedpkg \
        gcc \
        gcc-c++ \
        git \
        koji \
        krb5-workstation \
        libffi-devel \
        mock-scm \
        openssl-devel \
        python \
        python-devel \
        python-docutils \
        python-flask \
        python-gobject-base \
        python-m2ext \
        python-mock \
        python-qpid \
        python-solv \
        python-sqlalchemy \
        python-virtualenv \
        python-futures \
        python3 \
        python3-devel \
        python3-docutils \
        redhat-rpm-config \
        redhat-rpm-config \
        rpm-build \
        swig \
        https://kojipkgs.fedoraproject.org//packages/libmodulemd/1.1.3/1.fc27/x86_64/libmodulemd-1.1.3-1.fc27.x86_64.rpm
    cd /opt/module_build_service
    python setup.py develop
    python setup.py egg_info
    ln -s /opt/module_build_service/conf /etc/module-build-service
    pip install -r test-requirements.txt
SCRIPT

$script_services = <<SCRIPT_SERVICES
    cd /opt/module_build_service
    mbs-upgradedb > /tmp/mbs-base.out 2>&1
    fedmsg-relay < /dev/null >& /tmp/fedmsg-relay.out &
    fedmsg-hub < /dev/null >& /tmp/fedmsg-hub.out &
    mbs-frontend < /dev/null >& /tmp/mbs-frontend.out &
SCRIPT_SERVICES

Vagrant.configure("2") do |config|
  config.vm.box = "fedora/27-cloud-base"
  config.vm.synced_folder "./", "/opt/module_build_service"
  # Disable the default share
  config.vm.synced_folder ".", "/vagrant", disabled: true
  config.vm.network "forwarded_port", guest_ip: "0.0.0.0", guest: 5000, host: 5000
  config.vm.network "forwarded_port", guest_ip: "0.0.0.0", guest: 13747, host: 13747
  config.vm.provision "shell", inline: $script
  config.vm.provision "shell", inline: $script_services, run: "always"
  config.vm.provider "libvirt" do |v, override|
    override.vm.synced_folder "./", "/opt/module_build_service", type: "sshfs", sshfs_opts_append: "-o nonempty"
    v.memory = 1024
    #v.cpus = 2
  end
  config.vm.provider "virtualbox" do |v|
    v.memory = 1024
    #v.cpus = 2
  end
end
