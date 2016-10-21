#! /bin/sh -e

sudo docker build -f jenkins-check-Dockerfile  -t module_build_service/jenkins-check-24 .
sudo docker run module_build_service/jenkins-check-24
