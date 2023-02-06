#!/bin/bash


python3 main.py \
    --docker-image test-image \
    --bash-command $'pip install pip -U && pip
install tqdm && python -c \"import time\ncounter = 0\nwhile
True:\n\tprint(counter)\n\tcounter = counter + 1\n\ttime.sleep(0.1)\"' \
    --aws-cloudwatch-group test-task-group-1 \
    --aws-cloudwatch-stream test-task-stream-1 \
    --aws-access-key-id $AWS_ACCESS_KEY_ID \
    --aws-secret-access-key $AWS_SECRET_ACCESS_KEY \
    --aws-region $AWS_REGION
