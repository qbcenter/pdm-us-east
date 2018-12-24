import boto3
import os 

print('Uploading lambda handlers...')
items = ['telemetry', 'logs']
for i, item in enumerate(items):
  os.system('aws lambda update-function-code --function-name {0}_lambda \
            --zip-file fileb://Lambda/{0}_lambda.zip --publish'.format(item))

print('Creating topic rules...')
items = ['telemetry', 'logs']
iot_client = boto3.client('iot')
for i, item in enumerate(items):
  fn_name = '{}_lambda'.format(item)
  fn_arn = boto3.client('lambda')\
    .get_function_configuration(FunctionName=fn_name)['FunctionArn']
  rule_name='{}_rule'.format(item)
  try:
    iot_client.create_topic_rule(
      ruleName=rule_name,
      topicRulePayload={
        'sql': "select * from '{}'".format(item),
        'actions': [{ 'lambda': {'functionArn': fn_arn}}],
        'awsIotSqlVersion': '2016-03-23',
        'ruleDisabled': False,
      })
  except:
    pass
