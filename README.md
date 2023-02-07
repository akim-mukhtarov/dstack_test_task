# Test task for Dstack
Python program that redirects output logs of a container to AWS Cloudwatch.
This solution utilizes Docker builtin AWS logs driver, `awslogs`.

## Prerequisites
- Python >= 3.6.9
- Docker Engine 20.02
- AWS credentials with Cloudwatch Agent permissions
- Sudo privileges

## Arguments
1. A name of a Docker image
2. A bash command (to run inside the Docker image)
3. A name of an AWS CloudWatch group
4. A name of an AWS CloudWatch stream
5. AWS credentials
6. A name of an AWS region

## Example
```sh
python main.py --docker-image python --bash-command $'pip install pip -U && pip
install tqdm && python -c \"import time\ncounter = 0\nwhile
True:\n\tprint(counter)\n\tcounter = counter + 1\n\ttime.sleep(0.1)\"'
--aws-cloudwatch-group test-task-group-1 --aws-cloudwatch-stream test-task-stream-1
--aws-access-key-id ... --aws-secret-access-key ... --aws-region ...
```

## How to run

The following code demonstrates logs redirection of a sample command that
runs dependecies installation, calls Python interpreter and starts counting in infinite loop.
You should see the logs in a few minutes in Cloudwatch Console.
```sh
AWS_ACCESS_KEY_ID=<aws-access-key-id>
AWS_SECRET_ACCESS_KEY=<aws-secret-access-key>
AWS_REGION=<aws-region>
# Python stuff
python3 -m venv venv
source venv/bin/activate
python3 -m pip install -r requirements.txt
# test.sh will run the programm with sample script and image name
cd dtask_test_task
sudo chmod +x test.sh && ./test.sh
```

## Functionality
- The program creates a Docker container using the given Docker image name, and
the given bash command. If Docker container with specified image name already exists,
it creates a new container using this image and ignores input command.
- The program handles the output logs of the container and send them to the given
AWS CloudWatch group/stream using the given AWS credentials. If the corresponding
AWS CloudWatch group or stream does not exist, it creates it using the given
AWS credentials.
- The program behaves properly regardless of how much or what kind of logs the
container outputs.
- The profram handles SIGINT and SIGTERM
