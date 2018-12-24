import uuid
import time
import shutil
import os
import signal
import json
import requests
import random
import datetime
import dateutil.parser
import logging
from base64 import b64encode, b64decode
from hashlib import sha256
from urllib.parse import quote_plus, urlencode
from hmac import HMAC
import boto3
from http import HTTPStatus
import subprocess
import sys
from devices import SimulatorFactory

AWS_IOT_DIR = os.environ['AWS_IOT_DIR']
logging.log(logging.WARNING, 'AWS_IOT_DIR: %s' % (AWS_IOT_DIR))

class AwSIoT:
    def __init__(self):
        self.client = boto3.client('iot')
        self.host = self.client.describe_endpoint(endpointType='iot:Data-ATS')['endpointAddress']
        self.aws_iot_dir = AWS_IOT_DIR
        self.policy_name = 'default_policy'
        self.__create_policy()
        self.thing_group_name = 'simluated_thing_group'
        self.__create_thing_group()
        self.thing_type_name = 'rotation_machine'
        self.__create_thing_type()
        self.__simulator_script = self.aws_iot_dir + '/run_simulator.py'
        logging.log(logging.WARNING, 'run_simulator: %s' % (self.__simulator_script))

    def create_thing(self, thing_name, simulation_properties):
        self.client.create_thing(thingName=thing_name, thingTypeName=self.thing_type_name)
        
        # set default shadow
        h1 = simulation_properties['h1'] if 'h1' in simulation_properties else random.uniform(0.8, 0.95) 
        h2 = simulation_properties['h2'] if 'h2' in simulation_properties else random.uniform(0.8, 0.95) 
        
        state_init = {'h1': h1, 'h2': h2, 'pid': -1}
        state = {'desired': state_init, 'reported': state_init}

        # provision thing
        cert_id, cert_pem_filepath, private_key_filepath, root_ca_path = self.__create_certificate(thing_name)
        
        self.__register_thing(thing_name, self.thing_type_name, cert_id, self.policy_name)

        # register thing to simualted thing group
        self.__register_thing_to_simulated_group(thing_name)

        return AwSIoTThing(thing_name, state, root_ca_path, cert_pem_filepath, private_key_filepath)

    def __create_thing_group(self):
        self.client.create_thing_group(
            thingGroupName=self.thing_group_name,
            thingGroupProperties={
                'thingGroupDescription': 'A thing group for simulated devices'
        })

    def __create_thing_type(self):
        self.client.create_thing_type(
            thingTypeName=self.thing_type_name,
            thingTypeProperties={
                'thingTypeDescription': 'Rotation machine'
        })

    def __register_thing_to_simulated_group(self, thing_name):
        self.client.add_thing_to_thing_group(
            thingGroupName=self.thing_group_name,
            thingName=thing_name,
        )

    def __create_certificate(self, thing_name):
        cert_dir =  os.path.join(self.aws_iot_dir, 'keys_certificates/{}'.format(thing_name))
        if not os.path.exists(cert_dir):
            os.makedirs(cert_dir)
            cert = self.client.create_keys_and_certificate(setAsActive=True)
            cert_id, cert_pem = cert['certificateId'], cert['certificatePem']
            public_key, private_key = cert['keyPair']['PublicKey'], cert['keyPair']['PrivateKey']
            cert_pem_filepath = cert_dir + '/{}.{}.cert.pem'.format(thing_name, cert_id)
            public_key_filepath = cert_dir + '/{}.{}.public.key'.format(thing_name, cert_id)
            private_key_filepath = cert_dir + '/{}.{}.private.key'.format(thing_name, cert_id)
            path_content_pairs = [(cert_pem_filepath, cert_pem), (public_key_filepath, public_key), (private_key_filepath, private_key) ]
            for path, content in path_content_pairs:
                with open(path, 'w') as f:
                    f.write(content)
        else:
            cert_pem_filename = [f for f in os.listdir(cert_dir) if f.split('.')[-1] == 'pem'][0]
            cert_id = cert_pem_filename.split('.')[1]
            cert_pem_filepath = cert_dir + '/{}.{}.cert.pem'.format(thing_name, cert_id)
            public_key_filepath = cert_dir + '/{}.{}.public.key'.format(thing_name, cert_id)
            private_key_filepath = cert_dir + '/{}.{}.private.key'.format(thing_name, cert_id)

        root_ca_path = self.aws_iot_dir + '/keys_certificates/AmazonRootCA1.pem'
        return cert_id, cert_pem_filepath, private_key_filepath, root_ca_path
        
    def __create_policy(self):
        with open(self.aws_iot_dir + '/policy.json') as policy_json:
            policy_doc = str(json.load(policy_json)).replace(' ', '').replace('\'', '\"')
        try:
            policy = self.client.create_policy(policyName=self.policy_name, policyDocument=policy_doc)
        except: 
            policy = self.client.get_policy(policyName=self.policy_name)

        return policy
        
    def __register_thing(self, thing_name, thing_type_name, cert_id, policy_name):
        with open(os.path.join(self.aws_iot_dir, 'provisioning_template.json')) as provisioning_temp:
            provisioning_json = json.load(provisioning_temp)
        provisioning_json['Resources']['thing']['Properties']['ThingName'] = thing_name
        provisioning_json['Resources']['thing']['Properties']['ThingTypeName'] = thing_type_name
        provisioning_json['Resources']['certificate']['Properties']['CertificateId'] = cert_id
        provisioning_json['Resources']['policy']['Properties']['PolicyName'] = policy_name

        provisioning_doc = str(provisioning_json).replace(' ', '').replace('\'', '\"')
        self.client.register_thing(templateBody=provisioning_doc)

    def delete_thing(self, thing_name):
        principals = self.client.list_thing_principals(thingName=thing_name)['principals']
        for x in principals:
             self.client.detach_thing_principal(thingName=thing_name, principal=x)
             time.sleep(1)
        while len(self.client.list_thing_principals(thingName=thing_name)['principals']) > 0:
            pass
        for x in principals:
            cert_id = x.split('/')[-1]
            self.client.detach_policy(policyName=self.policy_name, target=x)
            self.client.update_certificate(certificateId=cert_id, newStatus='INACTIVE')
            self.client.delete_certificate(certificateId=cert_id)
        
        try:
            self.stop_thing_simulator(thing_name)
        except:
            pass

        self.client.delete_thing(thingName=thing_name)
        shutil.rmtree(self.aws_iot_dir + '/keys_certificates/' + thing_name)

    def get_thing_list(self):
        things = self.client.list_things_in_thing_group(
            thingGroupName=self.thing_group_name,
            maxResults=100
        )['things']
        logging.log(logging.WARNING, things)
        return things

    # should be used when thing already exists
    def get_iot_thing(self, thing_name):
        cert_id, cert_pem_filepath, private_key_filepath, root_ca_path = self.__create_certificate(thing_name)
        return AwSIoTThing(thing_name, None, root_ca_path, cert_pem_filepath, private_key_filepath)

    def run_thing_simulator(self, thing_name):
        cmd = ['python', self.__simulator_script, '-n', thing_name]
        pid = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, preexec_fn=os.setsid).pid
        logging.log(logging.WARNING, 'PID INIT ====== pid: %s gpid: %s' % (pid, os.getpgid(pid)))
        aws_iot_thing = self.get_iot_thing(thing_name)
        aws_iot_thing.update_shadow({'reported': {'pid': os.getpgid(pid)}})

    def stop_thing_simulator(self, thing_name):
        # terminate simulator process
        aws_iot_thing = self.get_iot_thing(thing_name)
        pid = aws_iot_thing.shadow['state']['reported']['pid']
        if pid != -1:
            os.killpg(pid, signal.SIGTERM)
        else:
            logging.log(logging.WARNING, 'PID ====== -1 !!!')
        aws_iot_thing.reset_simulator_state()

class AwSIoTThing:
    def __init__(self, thing_name, state, root_ca_path, certificate_path, private_key_path):
        self.data_client = boto3.client('iot-data')
        self.name = thing_name
        self.root_ca_path = root_ca_path
        self.certificate_path = certificate_path
        self.private_key_path = private_key_path
        if not state:
            self.shadow = json.loads(self.data_client.get_thing_shadow(thingName=thing_name)['payload'].read().decode('utf-8'))
        else:
            self.shadow = self.update_shadow(state)

    def send_message(self, message, topic='telemetry', qos=1):
        self.data_client.publish(topic=topic, qos=qos, payload=str.encode(json.dumps(message)))

    def send_reported_state(self, state, send_reported_state_callback = None, user_context = None):
        reported_state = {'reported': state}
        logging.log(logging.WARNING, reported_state)
        self.update_shadow(reported_state)

    def update_shadow(self, state):
        shadow_json = json.dumps({'state': state})
        shadow_payload = str.encode(shadow_json)
        thing_shadow_response = self.data_client.update_thing_shadow(thingName=self.name, payload=shadow_payload)
        return json.loads(thing_shadow_response['payload'].read().decode('utf-8'))

    def reset_simulator_state(self):
        self.update_shadow({'reported': {'pid': -1}})

    # TODO: Remove
    @staticmethod
    def __dummy_send_confirmation_callback(message, result, user_context):
        pass
        #print(result)

    @staticmethod
    def __dummy_send_reported_state_callback(status_code, user_context):
        pass
        # print(status_code) 

if __name__ == '__main__':
    pass
