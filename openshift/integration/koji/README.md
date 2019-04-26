MBS-Koji integration tests
==========================

### Background
This directory contains a set of Jenkins pipelines for building MBS container images and running integration tests between MBS and Koji. These are based on the [WaiverDB](https://pagure.io/waiverdb) [pipeline](https://pagure.io/waiverdb/blob/master/f/openshift) structure. Please see the extensive documentation there for information on the pipeline layout and workflows.

### Getting started

#### Deploying a Jenkins master
Before you can run these pipelines you need to have a Jenkins master configured to communicate with an OpenShift project. The simplest way to do this is to run your Jenkins master in your OpenShift project. The first time you create a `BuildConfig` with `strategy.type: JenkinsPipeline`, OpenShift will deploy a Jenkins master using the default settings. However, these pipelines will not run using the default settings. It is recommended that before creating any `BuildConfigs`, you setup your Jenkins master using:
```bash
make -C openshift/integration/koji/pipelines install-jenkins
```
This will deploy and configure your Jenkins master with the required set of plugins. **Note:** The Jenkins master will be configured to disable script security. Be very careful when running untrusted code, as scripts will have full access to your Jenkins environment. If you don't wish to disable script security, you may edit `openshift/integration/koji/pipelines/Makefile` to change that setting. You will need to allow scripts to access a number of Groovy/Java APIs before the pipelines will run successfully.

#### Configuring the pipelines
To load the pipelines into OpenShift (and Jenkins) run:
```bash
make -C openshift/integration/koji/pipelines install
```
This will create all the objects required for running the pipelines.

#### Configuring secrets for pushing images
If you're going to be pushing your images anywhere other than the OpenShift internal registry, you'll need to configure secrets which give you permission to push to that registry.

- Go to your registry dashboard and create a robot account.
- Backup your docker-config-json file (`$HOME/.docker/config.json`) if present.
- Run `docker login` with the robot account you just created to produce a new docker-config-json file.
- Create a new [OpenShift secret for a private registry] named `factory2-pipeline-registry-credentials` from your docker-config-json file:
```bash
  oc create secret generic factory2-pipeline-registry-credentials \
    --from-file=.dockerconfigjson="$HOME/.docker/config.json" \
    --type=kubernetes.io/dockerconfigjson
```

#### Configuring a Pagure API key
If you would like the pipelines to provide feedback on PRs and commits, you need to configure a Pagure API key.
- Go to your Pagure repository settings, and locate to the 'API Keys' section.
- Click on the `Create new key` button to add new API key with the `Flag a pull-request`, `Comment on a pull-request`, and `Flag a commit` permissions.
- Add your newly-created API key to OpenShift:
```bash
make -C openshift/integration/koji/pipelines update-pagure-api-key KEY=<value from Pagure>
```

#### Building a Jenkins slave image
Before you can run the pipelines, you need an image to use as the Jenkins slave. This step should be repeated any time the `Dockerfile` (`openshift/integration/koji/containers/jenkins-slave/Dockerfile`) for the Jenkins slaves is updated.
```bash
oc start-build mbs-premerge-jenkins-slave
```
**Note:** The `mbs-premerge-jenkins-slave` and `mbs-postmerge-jenkins-slave` jobs produce the same output. Either may be used.

#### Setting up Jenkins jobs

##### Polling
If you want the `premerge` and `postmerge` jobs to be triggered automatically based on SCM changes, you need to run the following jobs once manually, so Jenkins initates polling:
- mbs-polling-for-prs
- mbs-polling-for-master

##### Message bus
**Note:** This requires the `Red Hat CI Plugin` to be installed.
If you're using message bus integration to enable automatic triggering of test jobs and promotion, you need to run the trigger jobs once manually so Jenkins can setup required message consumers. The following jobs should be triggered manually:
- mbs-trigger-on-latest-tag
- mbs-trigger-on-stage-tag
- mbs-backend-greenwave-promote-to-stage
- mbs-backend-greenwave-promote-to-prod
- mbs-frontend-greenwave-promote-to-stage
- mbs-frontend-greenwave-promote-to-prod

[OpenShift secret for a private registry]: https://docs.openshift.com/container-platform/3.11/dev_guide/builds/build_inputs.html#using-docker-credentials-for-private-registries
