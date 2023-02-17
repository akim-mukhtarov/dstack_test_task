"""Redirect container logs to AWS Cloudwatch."""
import os
import sys
import stat
import signal
import time
import logging
import argparse
import subprocess
import typing as t
from functools import partial
from subprocess import PIPE, DEVNULL
from contextlib import contextmanager


logging.basicConfig()
logger = logging.getLogger(__file__)
logger.setLevel(logging.INFO)


def get_args():
    parser = argparse.ArgumentParser(description="Redirect container logs to AWS Cloudwatch")
    parser.add_argument('--docker-image', type=str, help='Name of a docker image')
    parser.add_argument('--bash-command', type=str, help='Bash command to run inside the container')
    parser.add_argument('--aws-cloudwatch-group', type=str, help='AWS Cloudwatch group')
    parser.add_argument('--aws-cloudwatch-stream', type=str, help='AWS Cloudwatch stream')
    parser.add_argument('--aws-access-key-id', type=str, help='')
    parser.add_argument('--aws-secret-access-key', type=str, help='')
    parser.add_argument('--aws-region', type=str)
    return parser.parse_args()


def stop_container(container_id: str) -> int:
    """Stop docker container using docker CLI, return exit code."""
    cmd = f"docker stop {container_id}"
    result = subprocess.run(cmd, shell=True, check=False)
    return result.returncode


def handle_sigint(signum, frame, container_id: str):
    """
    Handle SIGINT (also KeyboardInterrupt): shutdown container and exit.
    """
    logger = logging.getLogger(__file__)
    logger.info("Got SIGINT")
    logger.info("Stop container...")
    rc = stop_container(container_id)
    logger.info(f"Finished with exit code {rc}")
    logger.info("Exit gracefully")
    sys.exit(0)


def handle_sigterm(signum, frame, container_id: str):
    """
    Handle SIGTERM: shutdown container and exit.
    """
    logger = logging.getLogger(__file__)
    logger.info("Got SIGINT")
    logger.info("Stop container...")
    rc = stop_container(container_id)
    logger.info(f"Finished with exit code {rc}")
    logger.info("Exit gracefully")
    sys.exit(0)


def setup_aws_creds(aws_access_key_id: str,
                    aws_secret_access_key: str) -> None:
    """Add AWS credentials to Docker daemon settings."""
    # Make setup script executable
    dirname = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(dirname, "setup_creds.sh")
    st = os.stat(script)
    os.chmod(script, st.st_mode | stat.S_IEXEC)
    # Execute script
    cmd = f"{script} {aws_access_key_id} {aws_secret_access_key}"
    subprocess.run(cmd, stdout=DEVNULL, stderr=DEVNULL,
                   shell=True, check=True)


def run_in_container(docker_image: str,
                     bash_command: str,
                     aws_region: str,
                     aws_cloudwatch_group: str,
                     aws_cloudwatch_stream: str,
                     aws_access_key_id: str,
                     aws_secret_access_key) -> str:
    """
    Run command in a new docker container, redirecting
    logs to AWS Cloudwatch.
    """
    logger = logging.getLogger(__file__)
    # Setup AWS creds: consider better approach
    setup_aws_creds(aws_access_key_id, aws_secret_access_key)

    logger.info(f"Run in a new container...")
    cmd = (f"docker run --rm -d "
           f"--log-driver=awslogs "
           f"--log-opt awslogs-region={aws_region} "
           f"--log-opt awslogs-group={aws_cloudwatch_group} "
           f"--log-opt awslogs-stream={aws_cloudwatch_stream} "
           f"--log-opt awslogs-create-group=true "
           f"{docker_image} "
           f"sh -c '{bash_command}'")

    result = subprocess.run(cmd, stdout=PIPE, stderr=PIPE,
                            shell=True, check=True)

    stdout = result.stdout.decode('utf-8')
    logger.info('[stdout]')
    logger.info(stdout)

    stderr = result.stderr.decode('utf-8')
    if len(stderr):
        logger.info('[stderr]')
        logger.info(stderr)

    logger.info(f"Finished with exit code: {result.returncode}")
    container_id = stdout.strip()
    return container_id


def main():
    args = get_args()
    container_id = run_in_container(args.docker_image,
                                    args.bash_command,
                                    args.aws_region,
                                    args.aws_cloudwatch_group,
                                    args.aws_cloudwatch_stream,
                                    args.aws_access_key_id,
                                    args.aws_secret_access_key)
    # Set signal handlers
    sigint_handler = partial(handle_sigint, container_id=container_id)
    sigterm_handler = partial(handle_sigterm, container_id=container_id)
    signal.signal(signal.SIGINT, sigint_handler)
    signal.signal(signal.SIGTERM, sigterm_handler)
    # Wait for signals to exit
    logger = logging.getLogger(__file__)
    logger.info("Container is running. The logs should be in Cloudwatch "
                "Console in a few minutes.")
    logger.info("Press CTRL+C to stop container and exit")

    while True:
        time.sleep(1)


if __name__ == '__main__':
    main()

