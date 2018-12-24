import os
import io
import pickle
import random
import uuid
import datetime
import time
import json
import logging
import csv
import argparse
from multiprocessing import Pool, TimeoutError, cpu_count
from multiprocessing.dummy import Pool as DummyPool
from multiprocessing import Process
from devices import SimulatorFactory
import boto3
from aws_iot_helpers import AwSIoT, AwSIoTThing

def claim_and_run_device(aws_iot_thing, driver_id):
    simulation_properties = aws_iot_thing.shadow['state']['desired']
    state = {'h1': simulation_properties['h1'], 'h2': simulation_properties['h2']}
    aws_iot_thing.send_reported_state(state)

    def report_state(state):
        aws_iot_thing.send_reported_state(state)

    def send_telemetry(data):
        aws_iot_thing.send_message(data)

    def send_log(message, code, level):
        level_name = logging.getLevelName(level)
        data = {
            'machineID': aws_iot_thing.name,
            'level': level_name,
            'code': str(code) if len(str(code)) > 0 else 'None',
            'message': message,
            '_driver': driver_id,
            'timestamp': str(time.time())
        }
        aws_iot_thing.send_message(data, 'logs')

    device_simulator = SimulatorFactory.create('devices.engines.Engine', report_state, send_telemetry, send_log)
    if not device_simulator.initialize(aws_iot_thing.name, aws_iot_thing.shadow):
        logging.log(logging.WARNING, 'Simulator not initialized.')
        return
    
    device_simulator.run()

def device_driver(thing_name):
    driver_unique_id = str(uuid.uuid4())
    aws_iot = AwSIoT()
    aws_iot_thing = aws_iot.get_iot_thing(thing_name)
    while True:
        try:
            claim_and_run_device(aws_iot_thing,  driver_unique_id)
            logging.log(logging.WARNING, 'Driver {0} finished execution.'.format(driver_unique_id))
        except Exception as e:
            logging.log(logging.ERROR, 'Driver {0} threw an exception: {1}.'.format(driver_unique_id, str(e)))
            aws_iot_thing.reset_simulator_state()
            break
        except:
            logging.log(logging.ERROR, 'Driver {0} threw an exception.')
            aws_iot_thing.reset_simulator_state()
            break

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--thingName", action="store", required=True, dest="thing_name", help="Thing name")
    args = parser.parse_args()
    thing_name = args.thing_name

    process = Process(target=device_driver, args=(thing_name,))
    process.daemon = True
    process.start()
    logging.log(logging.WARNING, 'Procsss running...')

    while process.is_alive():
        time.sleep(3)
