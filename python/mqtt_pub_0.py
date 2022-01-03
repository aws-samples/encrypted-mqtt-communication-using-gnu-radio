# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import paho.mqtt.client as mqtt 
import boto3
import base64
from botocore.exceptions import ClientError
import logging

import pmt
import json
from datetime import datetime
from gnuradio import gr
import numpy as np

import sys


def on_connect(client, userdata, flags, rc): 
     if str(rc)=='0':
        gr.log.info("[mqtt publish] Connection successful")
     if str(rc)=='1':
        gr.log.info("[mqtt publish] Connection refused - incorrect protocol version")
     if str(rc)=='2':
        gr.log.info("[mqtt publish] Connection refused - invalid client indentifier") 
     if str(rc)=='3':
        gr.log.info("[mqtt publish] Connection refused - server unavailable")
     if str(rc)=='4':
        gr.log.info("[mqtt publish] Connection refused - bad username or password")
     if str(rc)=='5':
        gr.log.info("[mqtt publish] Connection refused - not authorised")

def on_disconnect(client, userdata, rc):
     if rc !=0:
        gr.log.info("[mqtt publish] Unexpected disconnect. Attempting to reconnect.")


def get_secret(secret_name, region_name):

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager', region_name=region_name)

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'DecryptionFailureException':
            gr.log.info("[mqtt publish] Secrets Manager can't decrypt the protected secret text using the provided KMS key")
            raise e
        elif e.response['Error']['Code'] == 'InternalServiceErrorException':
            gr.log.info("[mqtt publish] An error occurred on the server side.")
            raise e
        elif e.response['Error']['Code'] == 'InvalidParameterException':
            gr.log.info("[mqtt publish] You provided an invalid value for a parameter.")
            raise e
        elif e.response['Error']['Code'] == 'InvalidRequestException':
            gr.log.info("[mqtt publish] You provided a parameter value that is not valid for the current state of the resource.")
            raise e
        elif e.response['Error']['Code'] == 'ResourceNotFoundException':
            gr.log.info("[mqtt publish] We can't find the resource that you asked for.")
            raise e
    else:
        # Decrypts secret using the associated KMS CMK.
        # Depending on whether the secret is a string or binary, one of these fields will be populated.
        if 'SecretString' in get_secret_value_response:
            secret = get_secret_value_response['SecretString']
            return secret
        else:
            decoded_binary_secret = base64.b64decode(get_secret_value_response['SecretBinary'])
            return decoded_binary_secret


class mqtt_pub(gr.basic_block):
    """
    docstring for block mqtt_pub
    
    make(str hostname, int port, str topic, int qos, str secret_name, str region_name, bool debug)
    >mqtt subscribe 
    Publishes to topic on port with specified qos. 
    Pulls credentials from secret_name/ region_name. 
    debug enables logging of messages before publication on topic. 
    Args:
      hostname:
      port:
      topic:
      qos:
      secret_name:
      region_name:
      debug: 
    """
    def __init__(self, hostname="172.31.1.87", port=1883, topic="downlink", qos=1, secret_name="MqttCredentials", region_name="eu-west-1", debug=False):
        gr.sync_block.__init__(self, name="mqtt publish", in_sig=None, out_sig=None)
        self.topic = topic
        self.secret_name = secret_name
        self.region_name = region_name
        self.qos = qos
        self.port = port
        self.debug = debug

        #logging.basicConfig(level=logging.DEBUG) 
        #self.logger = logging.getLogger(__name__) 
       
        self.client = mqtt.Client()
        #self.client.enable_logger(self.logger)
        gr.log.info("[mqtt publish] Getting broker credentials from AWS Secrets Manager.")
        secret = get_secret(secret_name, region_name)
        username = secret.split(",")[0].split(":")[1].strip('"')
        password = secret.split(",")[1].split(":")[1].strip("}").strip('"')
        self.client.username_pw_set(username, password)
        gr.log.info("[mqtt publish] Connecting to hostname: " + hostname + " on port " + str(port))
        self.client.connect_async(hostname, port)
        self.client.on_connect = on_connect
        self.client.on_disconnect = on_disconnect
        self.client.loop_start()


        #Register message ports and handler function
        self.message_port_register_in(pmt.intern('pdu_in'))
        self.set_msg_handler(pmt.intern('pdu_in'), self.handle_msg)


    def handle_msg(self, msg):
        # transform from GNU Radio polymorphic data type to numpy array
        msg = pmt.to_python(msg)[1]
        
        # serialize numpy array to preprare for json 
        payload = msg.tolist()

        # create json message to send to MQTT broker
        msg_str = json.dumps({ 
            "payload" : payload,
            "time": datetime.strftime(datetime.utcnow(), "%y-%m-%dT%H:%M:%SZ")
        })
        
        if self.debug:
           gr.log.info("[mqtt publish] Message to publish: " + msg_str)
        
        #print("[mqtt publish]" + msg_str)
        self.client.publish(topic=self.topic, payload=msg_str, qos=self.qos)
