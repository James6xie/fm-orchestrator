# -*- mode: ruby -*-
# vi: set ft=ruby :

$script = <<SCRIPT
    dnf install -y python python-virtualenv python-devel libffi-devel redhat-rpm-config openssl-devel gcc gcc-c++ koji git
    pip install -r /opt/fm-orchestrator/src/requirements.txt
    pip install -r /opt/fm-orchestrator/src/test-requirements.txt
    cd /opt/fm-orchestrator/src
    mkdir -p /etc/rida
    cp -av koji.conf /etc/rida/
    python manage.py upgradedb
    ./generate_localhost_cert.sh
SCRIPT

Vagrant.configure("2") do |config|
  config.vm.box = "boxcutter/fedora24"
  config.vm.synced_folder "./", "/opt/fm-orchestrator/src"
  config.vm.network "forwarded_port", guest: 5000, host: 5000
  config.vm.provision "shell", inline: $script
  config.vm.provision :shell, inline: "cd /opt/fm-orchestrator/src && python manage.py runssl --debug &", run: "always"
end
