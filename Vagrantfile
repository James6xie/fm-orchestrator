# -*- mode: ruby -*-
# vi: set ft=ruby :

$script = <<SCRIPT
    echo "export KRB5CCNAME=FILE:/var/tmp/krbcc" > /etc/profile.d/module_build_service_developer_env.sh
    echo "export MODULE_BUILD_SERVICE_DEVELOPER_ENV=1" >> /etc/profile.d/module_build_service_developer_env.sh
    source /etc/profile.d/module_build_service_developer_env.sh
    dnf install -y \
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
        python-virtualenv \
        redhat-rpm-config \
        redhat-rpm-config \
        rpm-build \
        swig \
        systemd-devel
    systemctl enable fedmsg-relay
    systemctl start fedmsg-relay
    mkdir /etc/module-build-service/
    cd /tmp/module_build_service
    python setup.py develop
    mbs-upgradedb
    mbs-gencert
SCRIPT

Vagrant.configure("2") do |config|
  config.vm.box = "fedora/24-cloud-base"
  config.vm.synced_folder "./", "/tmp/module_build_service"
  config.vm.provision "file", source: "/var/tmp/krbcc", destination: "/var/tmp/krbcc", run: "always"
  config.vm.network "forwarded_port", guest: 5000, host: 5000
  config.vm.provision "shell", inline: $script
  config.vm.provision :shell, inline: "mbs-frontend &", run: "always"
  config.vm.provision :shell, inline: "mbs-daemon &", run: "always"
end
