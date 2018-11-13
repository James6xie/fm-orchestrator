Deploy MBS to OpenShift
=======================

## Build the container image for MBS backend

```bash
$ docker build openshift/backend \
    --tag mbs-backend:latest \
    --build-arg mbs_rpm=<MBS_RPM> \
    --build-arg mbs_messaging_umb_rpm=<MBS_MESSAGING_UMB_RPM> \
    --build-arg umb_ca_crt=<UMB_CA_CRT>
```

where:
* MBS_RPM is a path or URL to the Module Build Service RPM. If not specified,
  MBS [provided by
  Fedora](https://apps.fedoraproject.org/packages/module-build-service) will be
  installed in the image.
* MBS_MESSAGING_UMB_RPM is a path or URL to the [UMB Messaging
  Plugin](https://github.com/release-engineering/mbs-messaging-umb) RPM. If not
  provided, only `fedmsg` and `in_memory` will be available for messaging in the
  image.
* UMB_CA_CRT is a path or URL to the CA certificate of the message bus to be
  used by MBS.

## Build the container image for MBS frontend

The frontend container image is built on top of the backend image, which should
be available as `mbs-backend:latest`.

```bash
$ docker build openshift/frontend \
    --tag mbs-frontend:latest
```

## Deploy MBS

```bash
$ oc process -f openshift/mbs-test-template.yaml \
    -p TEST_ID=123 \
    -p MBS_BACKEND_IMAGE=<MBS_BACKEND_IMAGE> \
    -p MBS_FRONTEND_IMAGE=<MBS_FRONTEND_IMAGE> \
    -p MESSAGING_CERT=$(base64 -w0 <messaging.crt>) \
    -p MESSAGING_KEY=$(base64 -w0 <messaging.key>) \
    -p KOJI_CERT=$(base64 -w0 <koji.crt>) \
    -p KOJI_SERVERCA=$(base64 -w0 <koji_ca_cert.crt>) \
    -p KOJI_URL=<KOJI_URL> \
    -p STOMP_URI=<STOMP_URI> | oc apply -f -
```

Use `oc process parameters` to learn more about template parameters:

```bash
$ oc process --local -f openshift/mbs-test-template.yaml --parameters
NAME                 DESCRIPTION                                                                             GENERATOR           VALUE
TEST_ID              Short unique identifier for this test run (e.g. Jenkins job number)                                         
MBS_BACKEND_IMAGE    Image to be used for MBS backend deployment                                                                 172.30.1.1:5000/myproject/mbs-backend:latest
MBS_FRONTEND_IMAGE   Image to be used for MBS frontend deployment                                                                172.30.1.1:5000/myproject/mbs-frontend:latest
MESSAGING_CERT       base64 encoded SSL certificate for message bus authentication                                               
MESSAGING_KEY        base64 encoded SSL key for message bus authentication                                                       
KOJI_CERT            base 64 encoded client certificate used to authenticate with Koji                                           
KOJI_SERVERCA        base64 encoded certificate of the CA that issued the HTTP server certificate for Koji                       
DATABASE_PASSWORD                                                                                            expression          [\w]{32}
STOMP_URI            Messagebus URI                                                                                              
KOJI_URL             Top level URL of the Koji instance to use. Without a '/' at the end.                                        
```

## Delete MBS

```bash
$ oc delete dc,deploy,pod,configmap,secret,svc,route -l app=mbs
```
