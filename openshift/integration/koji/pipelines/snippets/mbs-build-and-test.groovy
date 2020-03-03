stage('Prepare repo and env') {
  steps {
    script {
      // Generate a version-release number for the target Git commit
      def version = sh(script: """grep -m 1 -P -o '(?<=version=")[^"]+' setup.py""", returnStdout: true).trim()
      def build_suffix = ".jenkins${currentBuild.id}.git${env.GIT_COMMIT.take(7)}"
      env.RESULTING_TAG = "${version}${build_suffix}"

      def resp = httpRequest params.MBS_SPEC_FILE
      def spec_file_name = params.MBS_SPEC_FILE.split("/").last()
      writeFile file: spec_file_name, text: resp.content

      env.ENVIRONMENT = 'dev'
      // Add celery dependency and removy config.py - should be removed after spec is updated to v3
      sh """
        sed -i \
            -e 's/Version:.*/Version:        ${version}/' \
            -e 's/%{?dist}/${build_suffix}%{?dist}/' \
            -e 's|\\(^BuildRequires:  python3-dnf\\)|\\1\\nBuildRequires:  python3-celery|' \
            -e 's|\\(^Requires:  python3-dnf\\)|\\1\\nRequires:  python3-celery|' \
            -e '/%config(noreplace) %{_sysconfdir}\\/module-build-service\\/config.py/d' \
            ${spec_file_name}

      """
      sh 'mkdir repos'
      params.EXTRA_REPOS.split().each {
        resp = httpRequest it
        writeFile file: "repos/${it.split("/").last()}", text: resp.content
      }
      sh """
        sed -i \
            -e '/enum34/d' \
            -e '/funcsigs/d' \
            -e '/futures/d' \
            -e '/koji/d' \
            requirements.txt
      """
      sh """
        sed -i \
            -e 's/py.test/py.test-3/g' \
            -e '/basepython/d' \
            -e '/sitepackages/a setenv = PYTHONPATH={toxinidir}' \
            tox.ini
      """
    }
  }
}
stage('Build backend image') {
  environment {
    BACKEND_BUILDCONFIG_ID = "mbs-backend-build-${currentBuild.id}-${UUID.randomUUID().toString().take(7)}"
  }
  steps {
    script {
      openshift.withCluster() {
        openshift.withProject(env.PIPELINE_ID) {
          // OpenShift BuildConfig doesn't support specifying a tag name at build time.
          // We have to create a new BuildConfig for each image build.
          echo 'Creating a BuildConfig for mbs-backend build...'
          def created = new Date().format("yyyy-MM-dd'T'HH:mm:ss'Z'", TimeZone.getTimeZone('UTC'))
          def template = readYaml file: 'openshift/backend/mbs-backend-build-template.yaml'
          def processed = openshift.process(template,
            '-p', "NAME=${env.BACKEND_BUILDCONFIG_ID}",
            '-p', "MBS_GIT_REPO=${params.GIT_REPO}",
            // A pull-request branch, like pull/123/head, cannot be built with commit ID
            // because refspec cannot be customized in an OpenShift build.
            '-p', "MBS_GIT_REF=${env.PR_NO ? env.GIT_REPO_REF : env.GIT_COMMIT}",
            '-p', "MBS_BACKEND_IMAGESTREAM_NAME=${params.MBS_BACKEND_IMAGESTREAM_NAME}",
            '-p', "MBS_BACKEND_IMAGESTREAM_NAMESPACE=${env.PIPELINE_ID}",
            '-p', "MBS_IMAGE_TAG=${env.RESULTING_TAG}",
            '-p', "EXTRA_RPMS=${params.EXTRA_RPMS}",
            '-p', "CREATED=${created}"
          )
          def build = c3i.buildAndWait(script: this, objs: processed, '--from-dir=.')
          def ocpBuild = build.object()
          env.BACKEND_IMAGE_DIGEST = ocpBuild.status.output.to.imageDigest
          def ref = ocpBuild.status.outputDockerImageReference
          def repo = ref.tokenize(':')[0..-2].join(':')
          env.BACKEND_IMAGE_REPO = repo
          env.BACKEND_IMAGE_REF = repo + '@' + env.BACKEND_IMAGE_DIGEST
          echo "Built image ${env.BACKEND_IMAGE_REF}, digest: ${env.BACKEND_IMAGE_DIGEST}, tag: ${env.RESULTING_TAG}"
        }
      }
    }
  }
  post {
    failure {
      echo "Failed to build mbs-backend image ${env.RESULTING_TAG}."
    }
  }
}
stage('Build frontend image') {
  environment {
    FRONTEND_BUILDCONFIG_ID = "mbs-frontend-build-${currentBuild.id}-${UUID.randomUUID().toString().take(7)}"
  }
  steps {
    script {
      openshift.withCluster() {
        openshift.withProject(env.PIPELINE_ID) {
          // OpenShift BuildConfig doesn't support specifying a tag name at build time.
          // We have to create a new BuildConfig for each image build.
          echo 'Creating a BuildConfig for mbs-frontend build...'
          def created = new Date().format("yyyy-MM-dd'T'HH:mm:ss'Z'", TimeZone.getTimeZone('UTC'))
          def template = readYaml file: 'openshift/frontend/mbs-frontend-build-template.yaml'
          def processed = openshift.process(template,
            '-p', "NAME=${env.FRONTEND_BUILDCONFIG_ID}",
            '-p', "MBS_GIT_REPO=${params.GIT_REPO}",
            // A pull-request branch, like pull/123/head, cannot be built with commit ID
            // because refspec cannot be customized in an OpenShift build.
            '-p', "MBS_GIT_REF=${env.PR_NO ? env.GIT_REPO_REF : env.GIT_COMMIT}",
            '-p', "MBS_FRONTEND_IMAGESTREAM_NAME=${params.MBS_FRONTEND_IMAGESTREAM_NAME}",
            '-p', "MBS_FRONTEND_IMAGESTREAM_NAMESPACE=${env.PIPELINE_ID}",
            '-p', "MBS_IMAGE_TAG=${env.RESULTING_TAG}",
            '-p', "MBS_BACKEND_IMAGESTREAM_NAME=${params.MBS_BACKEND_IMAGESTREAM_NAME}",
            '-p', "MBS_BACKEND_IMAGESTREAM_NAMESPACE=${env.PIPELINE_ID}",
            '-p', "CREATED=${created}"
          )
          def build = c3i.buildAndWait(script: this, objs: processed, '--from-dir=.')
          def ocpBuild = build.object()
          env.FRONTEND_IMAGE_DIGEST = ocpBuild.status.output.to.imageDigest
          def ref = ocpBuild.status.outputDockerImageReference
          def repo = ref.tokenize(':')[0..-2].join(':')
          env.FRONTEND_IMAGE_REPO = repo
          env.FRONTEND_IMAGE_REF = repo + '@' + env.FRONTEND_IMAGE_DIGEST
          env.FRONTEND_IMAGE_TAG = env.RESULTING_TAG
          env.RESULTING_IMAGE_REPOS = "${env.BACKEND_IMAGE_REPO},${env.FRONTEND_IMAGE_REPO}"
          echo "Built image ${env.FRONTEND_IMAGE_REF}, digest: ${env.FRONTEND_IMAGE_DIGEST}, tag: ${env.FRONTEND_IMAGE_TAG}"
          env.REUSE_PROJECT = "true"
        }
      }
    }
  }
  post {
    failure {
      echo "Failed to build mbs-frontend image ${env.RESULTING_TAG}."
    }
  }
}
{% include "mbs-integration-test.groovy" %}
