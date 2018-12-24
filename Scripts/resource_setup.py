import os 
import uuid

bucket_name = 'pdm-sagemaker-{}'.format(uuid.uuid1().hex)
script_dir = 's3://{}/scripts/'.format(bucket_name)

print("Creating S3 bucket '{}'".format(bucket_name))
os.system("aws s3 mb s3://{}".format(bucket_name))
os.system("aws s3 cp Notebooks/emr-install-my-jupyter-libraries.sh {}".format(script_dir))

print('Creating Kinesis Streams...')
os.system("aws kinesis create-stream --stream-name telemetry_stream --shard-count 10")
os.system("aws kinesis create-stream --stream-name logs_stream --shard-count 10")

print('Creating Dynamodb tables...')
os.system("python Scripts/generate_table.py logs_db telemetry_db")