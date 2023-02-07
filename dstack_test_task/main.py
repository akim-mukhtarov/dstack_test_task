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
from jinja2 import Environment, FileSystemLoader, select_autoescape


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


def create_shell_script(content: str) -> str:
    """Create shell sript with specified content."""
    script_name = "tmp.sh"
    with open(script_name, 'w') as bash_script:
        bash_script.write("#!/bin/bash\n")
        bash_script.write(content)
    return script_name


def create_python_dockerfile(bash_command: str) -> None:
    """Create Dockerfile from Jinja template."""
    env = Environment(loader=FileSystemLoader('templates/'),
                      autoescape=select_autoescape())
    template = env.get_template("Dockerfile.template.jinja")
    # Write command to a file so we don't care about proper
    # escaping of multiline commands in Dockerfile
    script_name = create_shell_script(content=bash_command)
    stream = template.stream(bash_script=script_name)
    stream.dump('Dockerfile')


def create_docker_image(image_name: str,
                        bash_command: str) -> None:
    create_python_dockerfile(bash_command)
    logger = logging.getLogger(__file__)
    logger.info("Start building...")
    # Build and wait for finish
    cmd = f"sudo docker build -t {image_name} ."
    result = subprocess.run(cmd, stdout=PIPE, stderr=PIPE,
                            shell=True, check=True)

    stdout = result.stdout.decode('utf-8')
    logger.info('[stdout]')
    logger.info(stdout)

    stderr = result.stderr.decode('utf-8')
    if len(stderr):
        logger.info('[stderr]')
        logger.info(stderr)

    logger.info(f"Build finished with exit code: {result.returncode}")


def setup_aws_creds(aws_access_key_id: str,
                    aws_secret_access_key: str) -> None:
    """Add AWS credentials to Docker server settings."""
    # Make setup script executable
    dirname = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(dirname, "setup_creds.sh")
    st = os.stat(script)
    os.chmod(script, st.st_mode | stat.S_IEXEC)
    # Execute script
    cmd = f"{script} {aws_access_key_id} {aws_secret_access_key}"
    subprocess.run(cmd, stdout=DEVNULL, stderr=DEVNULL,
                   shell=True, check=True)


def docker_image_exists(image_name: str) -> bool:
    """Check whether docker image with specified name exists."""
    cmd = f"docker inspect --type=image {image_name}"
    result = subprocess.run(cmd, stdout=DEVNULL, stderr=DEVNULL, shell=True)
    return result.returncode == 0


def run_container(image_name: str,
                  bash_command: str,
                  aws_region: str,
                  aws_cloudwatch_group: str,
                  aws_cloudwatch_stream: str,
                  aws_access_key_id: str,
                  aws_secret_access_key: str) -> str:
    """
    Run command in a new docker container, redirecting
    logs to AWS Cloudwatch.
    Container image will be created if doesn't exist.
    """
    logger = logging.getLogger(__file__)

    if not docker_image_exists(image_name):
        create_docker_image(image_name, bash_command)
    else:
        logger.info(f"Image {image_name} already exists.")
    # add AWS credentials to Docker server settings
    setup_aws_creds(aws_access_key_id, aws_secret_access_key)
    timestamp = int(time.time())
    container_name = f"{image_name}-container-{timestamp}"
    cmd = (f"sudo docker run --name {container_name} "
           f"--log-driver=awslogs "
           f"--log-opt awslogs-region={aws_region} "
           f"--log-opt awslogs-group={aws_cloudwatch_group} "
           f"--log-opt awslogs-stream={aws_cloudwatch_stream} "
           f"--log-opt awslogs-create-group=true "
           f"-d {image_name}")

    logger.info("Run in a new container")
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
    return container_name


def stop_container(container_name: str) -> int:
    """Stop docker container using docker CLI, return exit code."""
    cmd = f"sudo docker stop {container_name}"
    result = subprocess.run(cmd, shell=True, check=False)
    return result.returncode


def handle_sigint(signum, frame, container_name: str):
    """
    Handle SIGINT (also KeyboardInterrupt): shutdown container and exit.
    """
    logger = logging.getLogger(__file__)
    logger.info("Got SIGINT")
    logger.info("Stop container...")
    rc = stop_container(container_name)
    logger.info(f"Finished with exit code {rc}")
    logger.info("Exit gracefully")
    sys.exit(0)


def handle_sigterm(signum, frame, container_name: str):
    """
    Handle SIGTERM: shutdown container and exit.
    """
    logger = logging.getLogger(__file__)
    logger.info("Got SIGTERM")
    logger.info("Stop container...")
    rc = stop_container(container_name)
    logger.info(f"Finished with exit code {rc}")
    logger.info("Exit gracefully")
    sys.exit(0)


def main():
    args = get_args()
    container_name = run_container(args.docker_image,
                                   args.bash_command,
                                   args.aws_region,
                                   args.aws_cloudwatch_group,
                                   args.aws_cloudwatch_stream,
                                   args.aws_access_key_id,
                                   args.aws_secret_access_key)
    # Set signal handlers
    sigint_handler = partial(handle_sigint, container_name=container_name)
    sigterm_handler = partial(handle_sigterm, container_name=container_name)
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

