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
            gr.log.info("[mqtt subscribe] Secrets Manager can't decrypt the protected secret text using the provided KMS key")
            raise e
        elif e.response['Error']['Code'] == 'InternalServiceErrorException':
            gr.log.info("[mqtt subscribe] An error occurred on the server side.")
            raise e
        elif e.response['Error']['Code'] == 'InvalidParameterException':
            gr.log.info("[mqtt subscribe] You provided an invalid value for a parameter.")
            raise e
        elif e.response['Error']['Code'] == 'InvalidRequestException':
            gr.log.info("[mqtt subscribe] You provided a parameter value that is not valid for the current state of the resource.")
            raise e
        elif e.response['Error']['Code'] == 'ResourceNotFoundException':
            gr.log.info("[mqtt subscribe] We can't find the resource that you asked for.")
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



class mqtt_sub(gr.basic_block):
    """
    docstring for block mqtt_sbu
    
    make(str hostname, int port, str topic, int qos, str secret_name, str region_name, bool debug)
    >mqtt subscribe 
    Subscribes to topic on port with specified qos. 
    Pulls credentials from secret_name/ region_name. 
    debug enables logging of received messages on topic. 
    Args:
      hostname:
      port:
      topic:
      qos:
      secret_name:
      region_name:
      debug: 
    
    """
    def __init__(self, hostname="172.31.1.87", port=1883, topic="uplink", qos=1, secret_name="MqttCredentials", region_name="eu-west-1", debug=False):
        gr.sync_block.__init__(self, name="mqtt subscribe", in_sig=None, out_sig=None)
        self.topic = topic
        self.secret_name = secret_name
        self.region_name = region_name
        self.qos = qos
        self.port = port
        self.debug = debug
        
        #logging.basicConfig(level=logging.DEBUG) 
        #self.logger = logging.getLogger(__name__) 
       
        self.client = mqtt.Client()
        gr.log.info("[mqtt subscribe] Getting broker credentials from AWS Secrets Manager.")
        secret = get_secret(secret_name, region_name)
        username = secret.split(",")[0].split(":")[1].strip('"')
        password = secret.split(",")[1].split(":")[1].strip("}").strip('"')
        self.client.username_pw_set(username, password)
        gr.log.info("[mqtt subscribe] Connecting to hostname: " + hostname + " on port " + str(port))
        self.client.connect_async(hostname, port)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message=self.on_message
        self.client.loop_start()

        #Register message ports 
        self.message_port_register_out(pmt.intern('pdu_out'))
        
         

    def on_message(self, client, userdata, message):
        # decode payload data
        payload_dict = json.loads(message.payload.decode("utf-8"))

        # make np array out of payload object
        payload = np.array(payload_dict["payload"])
       
        # transform np array to unsigned 8 bit numbers 
        payload = payload.astype(np.uint8)

        if self.debug:
           gr.log.info("[mqtt subscribe] Received payload: " + str(payload))
        #print("[mqtt subscribe] " , payload)
        # tranform np array to GNU Radio polymorphic data type
        pmt_payload = pmt.to_pmt(payload)
        
        # send PDU on pdu_out port. Insert empty dict for PDU metadata
        self.message_port_pub(pmt.intern("pdu_out"), pmt.cons(pmt.make_dict(), pmt_payload))


    def on_connect(self, client, userdata, flags, rc): 
        if str(rc)=='0':
           gr.log.info("[mqtt subscribe] Connection successful")

           # Subscribing in on_connect() means that if we lose the connection and 
           # reconnect the subscriptions will be renewed
           gr.log.info("[mqtt subscribe] Subscribing to topic: " + self.topic)
           client.subscribe(topic=self.topic, qos=self.qos)
        if str(rc)=='1':
           gr.log.info("[mqtt subscribe] Connection refused - incorrect protocol version")
        if str(rc)=='2':
           gr.log.info("[mqtt subscribe] Connection refused - invalid client indentifier") 
        if str(rc)=='3':
           gr.log.info("[mqtt subscribe] Connection refused - server unavailable")
        if str(rc)=='4':
           gr.log.info("[mqtt subscribe] Connection refused - bad username or password")
        if str(rc)=='5':
           gr.log.info("[mqtt subscribe] Connection refused - not authorised")

    def on_disconnect(self, client, userdata, rc):
        if rc !=0:
           gr.log.info("[mqtt subscribe] Unexpected disconnect. Attempting to reconnect.")


  
