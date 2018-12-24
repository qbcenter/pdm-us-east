#!flask/bin/python
import sys, os, time, glob
# import requests
import json
import markdown
import jwt
import io
import csv
import collections
from urllib.parse import urlparse
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, Response, request,  redirect, url_for
from threading import Thread
from flask_breadcrumbs import Breadcrumbs, register_breadcrumb
from aws_iot_helpers import AwSIoT, AwSIoTThing
from http import HTTPStatus
import boto3
import logging
application = Flask(__name__)
application.debug = True

# Initialize Flask-Breadcrumbs
Breadcrumbs(app=application)

LOG_TABLE_NAME = os.environ['LOG_TABLE_NAME']
TELEMETRY_TABLE_NAME = os.environ['TELEMETRY_TABLE_NAME']

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'x-ms-token-aad-refresh-token' not in request.headers:
            pass
            #return redirect(url_for('setup'))
        return f(*args, **kwargs)
    return decorated_function

def get_identity():
    id_token = request.headers['x-ms-token-aad-id-token']
    return jwt.decode(id_token, verify=False)
'''
@application.context_processor
def context_processor():
    return dict(
        #user_name=get_identity()['name']
        version_info = VERSION_INFO)
'''
@application.route('/home')
@register_breadcrumb(application, '.', '首頁')
@login_required
def home():
    readme_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../README.md'))
    with open(readme_path, 'r', encoding='utf-8') as f:
        content = f.read()

    html = markdown.markdown(content)
    return render_template('home.html', content = html)

@application.route('/devices')
@register_breadcrumb(application, '.devices', '裝置模擬')
@login_required
def devices():
    return render_template('devices.html')

def error_response(error_code, message, http_status_code):
    data = {
        'code': error_code,
        'message': message
    }

    return Response(json.dumps(data), http_status_code, mimetype='application/json')

@application.route('/api/devices', methods=['GET'])
@login_required
def get_devices():
    aws_iot = AwSIoT()
    thing_names = aws_iot.get_thing_list()
    thing_names.sort()
    def pid_exists(pid):
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        else:
            return True
    def get_thing_simulation_state(thing_name):
        aws_iot_thing = aws_iot.get_iot_thing(thing_name)
        try:
            pid = aws_iot_thing.shadow['state']['reported']['pid']
            return pid > -1 and pid_exists(pid)
        except:
            return False

    thing_properties = json.dumps([{'thingName': name, 'isRunning': get_thing_simulation_state(name)} for name in thing_names])
    return Response(thing_properties, mimetype='application/json')

@application.route('/api/devices', methods=['PUT'])
@login_required
def create_thing():
    thing_name = str.strip(request.form['thingName'])

    if not thing_name:
        return error_response('INVALID_ID', 'Thing name cannot be empty.', HTTPStatus.BAD_REQUEST)

    try:
        simulation_properties = json.loads(request.form['simulationProperties'])
    except Exception as e:
        return error_response('INVALID_PARAMETERS', str(e), HTTPStatus.BAD_REQUEST)
    
    aws_iot = AwSIoT()
    
    try:
        aws_iot.create_thing(thing_name, simulation_properties)
    except Exception as e:
        return error_response('INVALID_ID', str(e), HTTPStatus.BAD_REQUEST)

    return Response()

@application.route('/api/devices/<thing_name>', methods=['DELETE'])
@login_required
def delete_device(thing_name):
    aws_iot = AwSIoT()
    aws_iot.delete_thing(thing_name)

    resp = Response()
    return resp

@application.route('/api/devices/<thing_name>/run', methods=['POST'])
@login_required
def run_thing_simulator(thing_name):
    aws_iot = AwSIoT()
    aws_iot.run_thing_simulator(thing_name)

    resp = Response()
    return resp

@application.route('/api/devices/<thing_name>/stop', methods=['POST'])
@login_required
def stop_thing_simulator(thing_name):
    aws_iot = AwSIoT()
    aws_iot.stop_thing_simulator(thing_name)

    resp = Response()
    return resp

def view_device_dlc(*args, **kwargs):
    device_id = request.view_args['device_id']
    url = urlparse(request.url)
    base_path = os.path.split(url.path)[0]
    return [{'text': device_id, 'url': '{0}/{1}'.format(base_path, device_id)}]

@register_breadcrumb(application, '.devices.device', '', dynamic_list_constructor=view_device_dlc)
@application.route('/devices/<device_id>')
@login_required
def devices_device(device_id):
    return render_template('devices_device.html', device_id = device_id)

@application.route('/api/devices/<thing_name>/logs', methods=['GET'])
@login_required
def get_device_logs(thing_name):
    db_client = boto3.client('dynamodb')
    log_entities = db_client.query(
                    TableName=LOG_TABLE_NAME,
                    ExpressionAttributeValues= {
                        ':thingname':{ 'S': thing_name },
                        ':code': { 'S': 'SIM_HEALTH' }
                    },
                    ExpressionAttributeNames= {
                        '#M': 'Message',
                        '#T': 'Timestamp',
                        '#L': 'Level',
                        '#C': 'Code'
                    },
                    KeyConditionExpression='PartitionKey = :thingname',
                    FilterExpression='#C <> :code',
                    ProjectionExpression='#M, #T, #L, #C, PartitionKey')['Items']

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(('Timestamp', 'Thing Name', 'Level', 'Code', 'Message'))

    for entity in sorted(log_entities, key=lambda e: e['Timestamp']['N']):
        level = entity['Level']['S']
        code = entity['Code']['S']
        message = entity['Message']['S']
        partitionKey = entity['PartitionKey']['S']
        timestamp = datetime.fromtimestamp(float(entity['Timestamp']['N'])).isoformat()
        row = (timestamp, partitionKey, level, code, message)
        writer.writerow(row)

    log_output = output.getvalue()

    resp = Response(log_output)
    resp.headers['Content-type'] = 'text/plain'
    return resp

@application.route('/api/devices/<thing_name>', methods=['GET'])
@login_required
def get_device(thing_name):
    db_client = boto3.client('dynamodb')
    health_history_entities = db_client.query(
                    TableName=LOG_TABLE_NAME,
                    ExpressionAttributeValues= {
                        ':thingname':{ 'S': thing_name },
                        ':code': { 'S': 'SIM_HEALTH' }
                    },
                    ExpressionAttributeNames= {
                        '#M': 'Message',
                        '#T': 'Timestamp',
                        '#C': 'Code'
                    },
                    KeyConditionExpression='PartitionKey = :thingname',
                    FilterExpression='#C = :code',
                    ProjectionExpression='#M, #T')['Items']

    health_history = []
    for entity in health_history_entities:
        timestamp = datetime.fromtimestamp(float(entity['Timestamp']['N'])).isoformat()
        message_json = json.loads(entity['Message']['S'])
        health_history.append((timestamp, message_json))

    health_history.sort(key = lambda x: x[0])

    health_history_by_index = {}
    for entry in health_history:
        timestamp = entry[0]
        indices_json = entry[1]
        for k, v in indices_json.items():
            if k not in health_history_by_index:
                health_history_by_index[k] = {'t': [], 'h': []}
            health_history_by_index[k]['t'].append(timestamp)
            health_history_by_index[k]['h'].append(v)

    response_json = {
        'health_history': health_history_by_index
    }

    resp = Response(json.dumps(response_json))
    resp.headers['Content-type'] = 'application/json'
    return resp

# @application.route('/modeling')
# @register_breadcrumb(application, '.modeling', 'Modeling')
# @login_required
# def analytics():
#     return render_template('modeling.html')

@application.route('/intelligence')
@register_breadcrumb(application, '.intelligence', '智慧預測')
@login_required
def intelligence():
    return render_template('intelligence.html')


@register_breadcrumb(application, '.intelligence.device', '', dynamic_list_constructor=view_device_dlc)
@application.route('/intelligence/<device_id>')
@login_required
def intelligence_device(device_id):
    return render_template('intelligence_device.html', device_id = device_id)

def make_timestamp(s):
    t = datetime(2018, 6, 21, 0, 0, 0) + timedelta(seconds=int(s))
    return t.isoformat()

@application.route('/api/intelligence')
@login_required
def get_intelligence():
    aws_iot = AwSIoT()
    thing_names = aws_iot.get_thing_list()
    
    db_client = boto3.client('dynamodb')
    pred_entities = db_client.query(
                    TableName='predictions',
                    ExpressionAttributeValues= {
                        ':key':{ 'S': '_INDEX_' },
                    },
                    ExpressionAttributeNames= {
                        '#P': 'Prediction',
                        '#D': 'Timestamp',
                        '#M': 'MachineID'
                    },
                    KeyConditionExpression='PartitionKey = :key',
                    ProjectionExpression='#P, #D, #M')['Items']
    
    pred_entities.sort(key=lambda x: x['Timestamp']['S'], reverse=True)
    predictions_by_thing = {p['MachineID']['S']: (p['Prediction']['S'], p['Timestamp']['S']) for p in  pred_entities}
    unknown_predictions = {thing_name: ('未知', None) for thing_name in thing_names if thing_name not in predictions_by_thing}
    combined = {**predictions_by_thing, **unknown_predictions}

    summary = {
        '被預測到的異常': 0,
        # '健康': 0,
        # '需要維修': 0,
        '未知': 0
    }

    summary_computed = collections.Counter(['被預測到的異常' if v[0].startswith('異常') else v[0] for v in combined.values()])
    summary.update(summary_computed)

    payload = {
        'predictions': [{
            'deviceId': k,
            'prediction': v[0],
            'lastUpdated': v[1],
        } for (k, v) in combined.items()],
        'summary': summary
    }
    logging.log(logging.WARNING, payload)

    payload_json = json.dumps(payload)
    resp = Response(payload_json)
    resp.headers['Content-type'] = 'application/json'
    return resp

@application.route('/api/intelligence/<device_id>/cycles')
@login_required
def get_intelligence_device_cycles(device_id):
    db_client = boto3.client('dynamodb')
    all_cycles = db_client.query(
                    TableName='cycles',
                    ExpressionAttributeValues= {
                        ':key':{ 'S': device_id },
                    },
                    ExpressionAttributeNames= {
                        '#T': 'Timestamp',
                        '#CS': 'CycleStart',
                        '#s1': 'SpeedDesiredMax',
                        '#s2': 'SpeedAvg',
                        '#s3': 'TemperatureAvg',
                        '#s4': 'TemperatureMax',
                        '#s5': 'PressureAvg',
                        '#s6': 'pressureMax',
                        '#s7': 'TemperatureAvgAvg',
                        '#s8': 'TemperatureMaxAvg',
                        '#s9': 'PressureAvgAvg',
                        '#s10': 'PressureMaxAvg',
                    },
                    KeyConditionExpression='MachineID = :key',
                    ProjectionExpression='#T, #CS, #s1, #s2, #s3,\
                    #s4, #s5, #s6, #s7, #s8, #s9, #s10')['Items']

    all_cycles.sort(key = lambda x: x['Timestamp']['S'], reverse=False)
    x = []
    y = {}

    for cycle in all_cycles:
        x.append(cycle['Timestamp']['S'])
        for key in cycle.keys():
            if key in ['PartitionKey', 'RowKey', 'CycleEnd', 'Timestamp', 'etag']:
                continue
            if key not in y:
                y[key] = []
            y[key].append(cycle[key]['S'])

    payload = {
        'x': x,
        'y': y
    }

    payload_json = json.dumps(payload)
    resp = Response(payload_json)
    resp.headers['Content-type'] = 'application/json'
    return resp

@application.route('/api/intelligence/<device_id>/predictions')
@login_required
def get_intelligence_device_predictions(device_id):
    db_client = boto3.client('dynamodb')
    predictions_1 = db_client.query(
                    TableName='predictions',
                    ExpressionAttributeValues= {
                        ':key':{ 'S': '_INDEX_' },
                        ':id':{ 'S': device_id },
                    },
                    ExpressionAttributeNames= {
                        '#P': 'Prediction',
                        '#D': 'Timestamp',
                        '#M': 'MachineID'
                    },
                    KeyConditionExpression='PartitionKey = :key',
                    FilterExpression='#M = :id',
                    ProjectionExpression='#P, #D, #M')['Items']
    predictions_2 = db_client.query(
                    TableName='predictions',
                    ExpressionAttributeValues= {
                        ':key':{ 'S': '_HISTORY_' },
                        ':id':{ 'S': device_id },
                    },
                    ExpressionAttributeNames= {
                        '#P': 'Prediction',
                        '#D': 'Timestamp',
                        '#M': 'MachineID'
                    },
                    KeyConditionExpression='PartitionKey = :key',
                    FilterExpression='#M = :id',
                    ProjectionExpression='#P, #D, #M')['Items']
    
    all_predictions = predictions_1 + predictions_2

    all_predictions = [(p['Timestamp']['S'], p['Prediction']['S']) for p in all_predictions]
    # all_predictions = [(make_timestamp(p['Timestamp']['S']), p['Prediction']['S']) for p in all_predictions]
    all_predictions.sort(key = lambda x: x[0], reverse=True)

    count = len(all_predictions)
    if count > 50:
        all_predictions = all_predictions[-50:-1]

    x = []
    y = []
    for prediction in all_predictions:
        x.append(prediction[0])
        y.append(prediction[1])

    payload = {
        'x': x,
        'y': y
    }

    payload_json = json.dumps(payload)
    resp = Response(payload_json)
    resp.headers['Content-type'] = 'application/json'
    return resp

if __name__ == "__main__":
    application.run('0.0.0.0', 80, debug=True)

