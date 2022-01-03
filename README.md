# Encrypted MQTT communication using GNU Radio on AWS

This is the guide for an encrypted MQTT data transfer solution for the
GNU Radio Software Defined Radio (SDR). Here you will find the design
overview, the steps required to implement the solution, verify the
implementation completed successfully, as well as operational
instructions.

![Solution Diagram](./docs/encrypted-MQTT-GNU-Radio-generic.png)

This document covers the whole design, which is split into two
CloudFormation templates. One for the SDR instance and one for the MQTT
broker.

The Mosquitto MQTT broker is deployed in an AWS region using multiple
availability zones. The broker is placed in a public subnet, as it needs
to communicate with the on-prem mission management software over the
Internet using TLS encryption. VPN and Direct Connect were not chosen as
they increase the cost of the solution.

TLS is terminated directly on the MQTT broker, forming an encrypted TLS
tunnel between MQTT clients and the MQTT broker. TLS is not terminated on the Elastic Load Balancers using Certificate Manager certificates, as this is not supported for the L7 MQTT protocol.
This design decision
provides end to end encryption and works around some paho-mqtt
complexities related to TLS handling. The MQTT broker hosts the
certification authority certificate, its own certificate and its own
private key. The MQTT clients have access to the same certificate
authority certificate. The client uses a username and password to
authenticate with the broker over the encrypted TLS tunnel.

Autoscaling is used for the MQTT server deployment. This provides the
ability to automatically recover from a failed MQTT server, or failure
of an AWS availability zone. Only one MQTT server will be active at a
time. As the MQTT broker is starting up it pulls credentials,
certificates and keys from AWS Secrets Manager. There is a watchdog
script on the Mosquitto broker that restarts the service in the event of
an unexpected failure.

Custom MQTT subscriber and publisher blocks have been developed by AWS
Professional Services for GNU Radio and placed on the SDR instance.
Broker credentials will be pulled securely from AWS Secrets manager. GNU
Radio publishes downlinked data to a custom MQTT topic and subscribes to
a custom MQTT topic for data to transmit to craft. No TLS encryption is
used for the SDR <-> MQTT broker traffic, as this traffic never
leaves AWS. The internal network load balancer that the SDR uses to talk
to the broker can only be accessed from within the VPCs.

The solution is currently supported in the following AWS regions:
Ireland, Stockholm, Bahrain, North Virginia, Ohio, and Oregon.

## MQTT broker installation procedure

Installation and configuration are a mix of manual steps and automated
deployment using CloudFormation.

The following resources need to be created manually:

-   TLS certificates for MQTT broker and clients

The following resources are created by the CloudFormation template:

-   VPC, 2 Public subnets, Internet gateway, VPC peering connection,
    Route table entries
-   MQTT credentials secret, certificates and keys in AWS Secrets
    manager
-   IAM Role for the MQTT broker that allows access to the credentials
    and TLS certificate in AWS Secrets Manager
-   Broker launch configuration for an Auto Scaling group
-   MQTT broker security group that allows:
    -   MQTT over TLS on port 8883 from a specified address range and
        created VPC
    -   MQTT on port 1883 from within the peered VPC
-   Internal network load balancer to route traffic from the SDR
    instance to the MQTT broker
-   Internet facing network load balancer to route traffic from on-prem
    to the MQTT broker
-   DNS record linking the domain used in the broker TLS certificate
    with the DNS name of the public network load balancer

## Create a DNS record for the public facing network load balancer

In order to facilitate TLS between the client and broker the broker’s
DNS identity must match its certificate. The easiest way to achieve this
is with a DNS A record linked to the public load balancer.  
  
You can use Amazon Route 53 to register a domain and a hosted zone for
your DNS needs. 

1.  [Register a new domain using Amazon Router
    53](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/domain-register.html#domain-register-procedure).
    For
    example: customer-domain.com

2.  [Create a public hosted
    zone](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/CreatingHostedZone.html) for
    newly registered domain using Amazon Route 53. 

## Create the TLS certificates 

Here you can find instructions on how to create TLS certificates using
openssl. These certificates will create an encrypted connection between
the MQTT broker and MQTT client just like the one between a web browser
client and a web server.

The broker requires the following certificates:

-   Certification authority (CA) certificate of the CA that has signed
    the broker certificate
-   CA certificated broker certificate
-   Broker private key

The client requires:
-   CA certificate of the CA that has signed the broker certificate

You can download [openssl for free from the
internet](https://www.openssl.org/). The commands below are the same for
Windows and Linux. We are going to create our own CA to sign the broker
certificate.

### Create a key pair for the CA
```bash
openssl genrsa -des3 -out ca.key 2048
```

This key should be password protected.

### Create a certificate for the CA using the CA key

```bash
openssl req -new -x509 -days 1460 -key ca.key -out ca.crt
```

This certificate is valid for 4 year.

### Create a key pair for the broker 

```bash
openssl genrsa -out server.key 2048
```


### Create a certificate request for the broker

In the **common name** section enter the DNS name that you will link
with a record to public network load balancer. For example, in
the Create a DNS record for the public facing network load
balancer section you created
the customer-domain.com domain and hosted
zone, the common name can
be mqtt.customer-domain.com  
This will be the static public DNS name of the broker, as the public
load balancer is fronting the broker. Should you have to rebuild the
stack the certificate will still be valid as it will be linked to a DNS
name that is independent of the network load balancer. If you change the
DNS name pointing to the public load balancer TLS encryption will fail.
As an example you can use mqtt.customer-domain as the record for the
public load balancer.

```bash
openssl req -new -out server.csr -key server.key
```

At the end do not send this to an CA as you are the CA.

### Use the CA key to sign the broker certificate

```bash
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365
```

This certificate is valid for 1 year.

### File review 

You should have the following files in your folder

-   ca.crt
-   ca.key
-   ca.srl
-   server.crt
-   server.csr
-   server.key

You will use ca.crt, server.crt and server.key as inputs to the MQTT broker
CloudFormation template. The values of these files will be securely
stored in AWS Secrets Manager. The CloudFormation template will give the
MQTT broker permissions to access these values.

Keep these files safe. The ca.key is used to create new certificates.

### Client configuration 

Your client will need the ca.crt file to establish a TLS connection with
the broker. When using the paho mqtt library use the client method
[tls\_set()](https://pypi.org/project/paho-mqtt/#tls-set). Call It
before calling the connect() method.

```python
client.tls\_set(ca\_certs=‘&lt;path-to-ca.crt&gt;’, tls\_version=2)
```

## Create the CloudFormation stack

Create a new CloudFormation stack using the mqtt-broker YAML template.
Guidance for each of the parameters is provider below. This template is
to be deployed in the Ohio region.

**Network Parameters**

-   VpcCidr: The CIDR range of the broker VPC. Must not overlap with the
    SDR VPC CIDR range.
-   PeerVpcId: The ID of the SDR VPC.
-   PeerVpcRegion: The AWS region of the SDR VPC
-   PeerVpcCIDRRange: The CIDR range of the peering SDR VPC

**EC2 MQTT Broker Parameters**

-   InstanceType: Do not change this
-   MQTTCidrBlock: The CIDR Block that the security group will allow
    MQTT over TLS access to the broker.
-   MQTTUsername: The username used by the MQTT clients to connect to
    the broker
-   MQTT Password: The password used by the MQTT clients to connect to
    the broker
-   CaCertitificateValue: The CA certificate of the CA. Only the value
    between the -----BEGIN CERTIFICATE----- and -----END
    CERTIFICATE----- tags.
-   ServerCertificateValue: The server certificate of the MQTT server.
    Only the value between the -----BEGIN CERTIFICATE----- and -----END
    CERTIFICATE----- tags.
-   ServerKeyValue: The server key of the MQTT server. Only the value
    between the -----BEGIN RSA PRIVATE KEY----- and -----END RSA PRIVATE
    KEY----- tags.
-   DomainName: Must match the common name of the broker TLS
    certificate. Domain name record associated with the TLS certificate
    to be assigned to the public Network Load Balacer.

The CloudFormation stack will complete fairly quickly and then spin up
the first EC2 Mosquitto MQTT broker instance as part of the autoscaling
group. The instance will install the need software and reboot to finish
the configuration. To check for any errors on the EC2 instance, [use
Session Manager to connect to the
instance](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/session-manager.html)
and run the command below.

```bash
cat /var/log/user-data.log
```

# Verifying the installation completed successfully

After completing the installation procedure follow the steps in this
section to confirm everything installed correctly. You will use the
mosquitto\_pub and mosquitto\_sub tools part of the Mosquitto
installation to test access to the broker from on-prem. Only IPs from
the MQTTCidrBlock CloudFormation parameter will be able to perform these
tests.

-   Download and install the [Mosquitto client programs for your
    system](https://mosquitto.org/download/)

-   You need the CA certificate file (ca.crt) on the test machine

-   Subscribe to the **downlink** topic in the broker using the command
    in a terminal:

    -   ```bash
        mosquitto_sub -h <DNS A record in front of public load balancer> -u <MQTTUsername> -P <MQTTPassword> --cafile <path to ca.crt> -p 8883 -t downlink -d
        ```

-   Publish to the **downlink** topic using the command in a separate
    terminal:

    -   ```bash
        mosquitto_pub -h <DNS A record in front of public load balancer> -u <MQTTUsername> -P <MQTTPassword> --cafile <path to ca.crt> -p 8883 -t downlink -d -m “Hello from GNU Radio”
        ```

-   You should see the message pop up in the first terminal

-   If it does not then follow the debug out and check the following:

    -   Status of MQTT broker in the EC2 console

    -   The security group of the MQTT broker. Check that you’ve entered
        the correct IP ranges.

    -   If you’re getting a TLS error verify that the certificate on the
        broker has the same CN (common name) at its DNS name. Use
        openssl to get the certificate and compare the CN to the address
        that you connected to. They must be the same. After the
        certificates, under the heading Server certificate check the CN
        of the subject.

        -  ```bash
            openssl s_client -connect <DNS A record in front of public load balancer>:8883 -showcert
            ```

    -   Status of the MQTT service on the broker. Log into the broker
        and run:

        -   ```bash 
            systemctl status mosquitto 
            ```

    -   If the mosquitto service is running, but you still cannot
        connect then stop the service and run it manually to get access
        to more debugging information

        -   ```bash
            sudo systemctl stop mosquitto
            ```

        -   ```bash 
            mosquitto -c /etc/mosquitto/conf.d/default.conf -v
            ```

# GNU Radio SDR installation procedure 

Installation and configuration is automated using CloudFormation and a
number of scripts which are executed within the user-data section of the
EC2 instances created by CloudFormation.

The following resources are created by the CloudFormation template:

-   GNU Radio EC2 instance
-   VPC peering connection between the MQTT broker VPC and SDR VPC
-   IAM Role for the GNU Radio EC2 instance that allows access to the
    MQTT credentials AWS Secrets Manager
-   GNU Radio EC2 security group that allows:
    -   SSH traffic on port 22 from specified IP range

During the installation, files are downloaded from an AWS-managed S3
bucket.

## Create the CloudFormation stack

Create a new CloudFormation stack using the gnu-radio YAML template.
Guidance for each of the parameters is provider below.

**General Parameters**

-   NotificationEmail: An email address to receive notifications
-   OsPassword: Enter a password without any special characters. This
    will be set for the ubuntu user on the GNU Radio instance. Avoid
    using characters in the password which are not CLI friendly such as
    spaces, !$\# etc.

**EC2 Instance Parameters**

-   SSHCidrBlock: An IP range/address which will have access to SSH on
    the EC2 servers. e.g. 10.12.34.0/24 or 10.12.34.2/32
-   SSHKeyName: The name of an SSH key to use when connecting to the EC2
    instances
-   VpcId: Id of VPC to place the EC2 instances
-   SubnetId: Id of Subnet to place the EC2 instances
-   SdrInstanceType: Select the instance type you would like to use
    (c5.4xlarge is usually sufficient)

**VPC Peering**

-   VpcPeeringConnectionID: The ID of the VPC peering connection between
    the MQTT broker and SDR VPCs – available as an output from the MQTT
    CFN template
-   PeerVpcCidrRange: The CIDR range of the peering MQTT broker VPC –
    available as an output from the MQTT CFN template
-   PeerVpcRouteTableId: The ID of the route table associated with the
    SDR subnet – can be found under the VPC service

**MQTT Parameters**

-   MqttDownlinkTopic: GNU Radio will publish downlinked data to this
    topic
-   MqttUplinkTopic: GNU Radio will publish downlinked data to this
    topic
-   MqttQos: Desired MQTT Quality of Service (QoS)
-   MqttBrokerDNSName: The DNS name of the mqtt broker private load
    balancer - available as an output from the MQTT CFN template
-   MqttBrokerCredentialsName: The name of the MQTT broker credentials
    stored in AWS Secrets Manager - available as an output from the MQTT
    CFN template
-   MqttBrokerCredentialsRegion: The AWS region where the MQTT broker
    credentials are stored in AWS Secrets Manager - available as an
    output from the MQTT CFN template
-   MqttBrokerCredentialsARN: The ARN of the MQTT broker credentials -
    available as an output from the MQTT CFN template

**Important Note:** During the creation of the CloudFormation stack, an
email will be sent to the address specified in the “NotificationEmail”
parameter. Ensure that you open the email and click the link to confirm
subscription. If this step is not done, important notification emails
will not be sent.

The CloudFormation stack will complete fairly quickly and then leave
further installation processes running on the EC2 instance. To check
progress on the EC2 instance, ssh to the instance and run the command
below.

```bash
tail -F /var/log/user-data.log
```

An email is sent to the provided email address when the GNU Radio
installation has completed on the EC2 instance. It should take about 45
minutes.

## Verify the installation completed successfully 

After receiving the SNS email which confirms the installation completed
on the GNU Radio EC2 instances, follow the steps in this section to
confirm everything is installed correctly.

1.  Start the EC2 instance
2.  Connect to the EC2 instance using VNC, using the instructions in the
    “Connecting to the GNU Radio instance using VNC” section of this
    document
3.  Check the `/var/log/user-data.log` file for errors using the command
    ```bash
    cat /var/log/user-data.log | more
    ```
4.  Check that GNU Radio Companion (GRC) runs ok by opening a terminal
    and typing `./s`, this is a small batch file that configures the
    GNU Radio environment then opens the GRC application.
5.  To verify the connection between the GNU Radio and the MQTT broker
    use the mqtt\_tester.grc recipe located in
    /home/ubuntu/sdr/recipes/. You will need to change the variables to
    match your configuration. You can find the parameters for your
    configuration in /home/ubuntu/sdr/aws-grautorun.json.
6.  Use the mosquitto\_sub client to test end to end connectivity. On a
    machine that can connect to the broker subscribe to a topic using
    the instruction in section 5.0 then run the mqtt\_tester.grc recipe
    with the appropriate parameters. Make sure the topics match. You
    should see the message sent from GNU Radio on the terminal of your
    machine.

**Important Note:** If you are unable to run the mqtt\_tester.grc recipe
this is caused by the way GNU Radio instantiates blocks in a GUI
flowgraph. Everything in the \_\_init\_\_ method of a block in a GUI
recipe GNU Radio tries to run when you open the recipe not when you run
it. However, parameters and variables are only passed to the block when
the recipe is run. Therefore, the block tries to instantiate itself with
the default parameters and getting the MQTT credentials is in the
\_\_init\_\_ part of the block, so it tries to do it with the
secret\_name=”MqttCredentials” and region\_name=”eu-west-1”, which is
most likely not the config for your secret. To fix this you have to
change the default parameters in the python code of the mqtt publish and
subscribe blocks. On the mqtt\_tester GUI GNU Radio recipe double click
on the mqtt publish block and click the open python code box at the top.
In the \_\_init\_\_ method show below change the default secret\_name
and region\_name variable to reflect those for your MQTT secret.

Save the file and repeat for the mqtt subscribe block. The error should
be resolved.

# Connecting to the GNU Radio instance using VNC

To test GNU Radio or edit flowgraphs, GNU Radio Companion (GRC) is used.

GRC needs a graphical user environment to run correctly. VNC is used to
connect to the Ubuntu desktop environment running on the EC2 instance.

It is recommended that TIger VNC is used as this has been reliable in
testing so far.

-   Download and install the Tiger VNC Client from
    [here](https://bintray.com/tigervnc/stable/tigervnc). Or use the
    following quick-links for
    [Linux](https://bintray.com/tigervnc/stable/download_file?file_path=tigervnc-1.10.1.x86_64.tar.gz),
    [Mac](https://bintray.com/tigervnc/stable/download_file?file_path=TigerVNC-1.10.1.dmg)
    and [64 bit
    Windows](https://bintray.com/tigervnc/stable/download_file?file_path=vncviewer64-1.10.1.exe).

## VNC Connection - Linux / Mac

-   Run the command below to connect to the EC2 instance using SSH and
    tunnel the VNC traffic over the SSH session.
    ```bash
    ssh -L 5901:localhost:5901 -i <path to pem file> ubuntu@<public ip address of EC2 instance>
    ```

-   Open the Tiger VNC Client application on your PC and connect to
    ‘localhost:1’
-   When prompted, enter the os password you provided to the
    CloudFormation template in the earlier step

## VNC Connection - Windows

7.  Download the open source ssh client Putty from
    [here](https://www.chiark.greenend.org.uk/~sgtatham/putty/latest.html)
8.  Open Putty and enter the public IP of the EC2 instance in the
    Session-&gt;Host Name (or IP Address) field.
9.  Enter ‘ubuntu’ in Connection-&gt;Data-&gt; Auto-login username
10. In Connection-&gt;SSH-&gt;Auth, browse to the correct PPK key file
    (private SSH key) for the EC2 instance
11. In Connection-&gt;SSH-&gt;Tunnels, enter 5901 in Source port, enter
    localhost:5901 in Destination, click Add
12. Click Session, enter a friendly name in Save Sessions, then click
    Save
13. Click Open to open the tunneled SSH session
14. Open the Tiger VNC Client application on your PC and connect to
    ‘localhost:1’
15. When prompted, enter the os password you provided to the
    CloudFormation template in the earlier step

