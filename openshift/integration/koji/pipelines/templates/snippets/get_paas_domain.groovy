if (!env.TRIGGER_NAMESPACE) {
  env.TRIGGER_NAMESPACE = readFile("/run/secrets/kubernetes.io/serviceaccount/namespace").trim()
}
if(!env.PAAS_DOMAIN) {
  openshift.withCluster() {
    openshift.withProject(env.TRIGGER_NAMESPACE) {
      def testroute = openshift.create('route', 'edge', "test-${env.BUILD_NUMBER}",  '--service=test', '--port=8080')
      def testhost = testroute.object().spec.host
      env.PAAS_DOMAIN = testhost.minus("test-${env.BUILD_NUMBER}-${env.TRIGGER_NAMESPACE}.")
      testroute.delete()
    }
  }
  echo "Routes end with ${env.PAAS_DOMAIN}"
}
