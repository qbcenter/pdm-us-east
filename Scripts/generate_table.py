import boto3
import time
from abc import ABC, abstractmethod
import logging
import os
import sys

LOG_TABLE_NAME = ''
TELEMETRY_TABLE_NAME = ''

class TableHanlder(ABC):
  def __init__(self, table_name):
    self.db_client = boto3.client('dynamodb')
    self.table_name = table_name

  def create_table(self, attributes, key_schema):
    table_name = self.table_name
    
    logging.log(logging.INFO, 'Creating %s...' % (table_name))

    if table_name not in self.db_client.list_tables()['TableNames']:
        self.db_client.create_table(
            TableName=table_name, 
            AttributeDefinitions=attributes,
            KeySchema=key_schema,
            BillingMode='PAY_PER_REQUEST'
        )
        time.sleep(3)
    else:
        pass

    while True:
        try:
            table_status = self.db_client.describe_table(TableName=table_name)['Table']['TableStatus']
            if table_status == 'ACTIVE':
                break
        except:
            time.sleep(1)

    logging.log(logging.INFO, '%s created.' % (table_name))

  def put_item(self, entity):
    self.db_client.put_item(TableName=self.table_name, Item=entity)

class LogTableHandler(TableHanlder):
  def __init__(self, table_name):
      super().__init__(table_name)

  def create_table(self):
    attributes = [  
        {'AttributeName':'PartitionKey', 'AttributeType':'S'}, 
        {'AttributeName':'Timestamp','AttributeType':'N'}
    ]
    key_schema = [
        {'AttributeName':'PartitionKey', 'KeyType':'HASH'},
        {'AttributeName':'Timestamp', 'KeyType':'RANGE'}
    ]
    super().create_table(attributes, key_schema)

class TelemetryTableHandler(TableHanlder):
  def __init__(self, table_name):
      super().__init__(table_name)

  def create_table(self):
    attributes = [  
        {'AttributeName':'MachineID', 'AttributeType':'S'},
        {'AttributeName':'Timestamp', 'AttributeType':'S'}
    ]
    key_schema = [
        {'AttributeName':'MachineID', 'KeyType':'HASH'},
        {'AttributeName':'Timestamp', 'KeyType':'RANGE'}
    ]
    super().create_table(attributes, key_schema)

if __name__ == '__main__':
    args = sys.argv
    LOG_TABLE_NAME = args[1]
    TELEMETRY_TABLE_NAME = args[2]
    LogTableHandler(LOG_TABLE_NAME).create_table()
    TelemetryTableHandler(TELEMETRY_TABLE_NAME).create_table()