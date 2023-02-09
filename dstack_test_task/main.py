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


def stop_container(container_name: str) -> int:
    """Stop docker container using docker CLI, return exit code."""
    cmd = f"docker stop {container_name}"
    result = subprocess.run(cmd, shell=True, check=False)
    return result.returncode


def handle_sigint(signum, frame, container_name: str, dockerfile_path: str):
    """
    Handle SIGINT (also KeyboardInterrupt): shutdown container and exit.
    """
    logger = logging.getLogger(__file__)
    logger.info("Got SIGINT")
    logger.info("Stop container...")
    rc = stop_container(container_name)
    logger.info(f"Finished with exit code {rc}")
    logger.info("Remove dockerfile...")
    os.remove(dockerfile_path)
    logger.info("Done")
    logger.info("Exit gracefully")
    sys.exit(0)


def handle_sigterm(signum, frame, container_name: str, dockerfile_path: str):
    """
    Handle SIGTERM: shutdown container and exit.
    """
    logger = logging.getLogger(__file__)
    logger.info("Got SIGTERM")
    logger.info("Stop container...")
    rc = stop_container(container_name)
    logger.info(f"Finished with exit code {rc}")
    logger.info("Remove dockerfile {dockerfile_path}...")
    os.remove(dockerfile_path)
    logger.info("Done")
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


def create_default_dockerfile(path, script_path) -> None:
    """Create Dockerfile from Jinja template."""
    env = Environment(loader=FileSystemLoader('templates/'),
                      autoescape=select_autoescape())
    template = env.get_template("Dockerfile.base.jinja")
    stream = template.stream(bash_script=script_path)
    stream.dump(path)


def create_extended_dockerfile(path, base_image: str, script_path) -> None:
    """Create Dockerfile from Jinja template."""
    env = Environment(loader=FileSystemLoader('templates/'),
                      autoescape=select_autoescape())
    template = env.get_template("Dockerfile.ext.jinja")
    stream = template.stream(base_image=base_image,
                             bash_script=script_path)
    stream.dump(path)


def build_docker_image(image_name, dockerfile_path) -> None:
    logger = logging.getLogger(__file__)
    logger.info("Start building...")
    logger.info(f"dockerfile path: {dockerfile_path}")
    cmd = f"docker build -f {dockerfile_path} -t {image_name} ."
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


def build_default_docker_image(image_name: str,
                               script_path: str) -> str:
    teimstamp = int(time.time())
    dirname = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(dirname, "tmp/Dockerfile.tmp")
    create_default_dockerfile(path, script_path)
    build_docker_image(image_name, path)
    return path


def build_extended_docker_image(base_image_name: str,
                                script_path: str) -> t.Tuple[str, str]:
    timestamp = int(time.time())
    dirname = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(dirname, f"tmp/Dockerfile.tmp-{timestamp}")
    create_extended_dockerfile(path, base_image_name, script_path)
    image_name = f"{base_image_name}-{timestamp}"
    build_docker_image(image_name, path)
    return path, image_name


def docker_image_exists(image_name: str) -> bool:
    """Check whether docker image with specified name exists."""
    cmd = f"docker inspect --type=image {image_name}"
    result = subprocess.run(cmd, stdout=DEVNULL, stderr=DEVNULL, shell=True)
    return result.returncode == 0


@contextmanager
def tmp_script_file(directory: str, content: str):
    """Create tmp script in `directory` with `content`, yield path."""
    logger = logging.getLogger(__file__)
    logger.info('Creating tmp script file...')

    timestamp = int(time.time())
    script_name = f"tmp_script_{timestamp}"
    script_path = os.path.join(directory, script_name)

    logger.info(f"Script name: {script_name}")
    logger.info(f"Script path: {script_path}")
    # Create dir if doesn't extis
    os.makedirs(os.path.dirname(script_path), exist_ok=True)
    with open(script_path, 'w') as file:
        file.write('#!/bin/bash\n')    # write shebang
        file.write(content)
    try:
        yield script_path
    finally:
        logger.info('Remove tmp script file...')
        os.remove(script_path)


def run_in_container(image_name: str,
                     bash_command: str,
                     aws_region: str,
                     aws_cloudwatch_group: str,
                     aws_cloudwatch_stream: str,
                     aws_access_key_id: str,
                     aws_secret_access_key) -> t.Tuple[str, str]:
    """
    Run command in a new docker container, redirecting
    logs to AWS Cloudwatch.
    If container image exists, new image will be created using
    it as a base layer, otherwise a new default image will be used.
    """
    logger = logging.getLogger(__file__)
    dirname = 'tmp'

    with tmp_script_file(dirname, bash_command) as script_path:
        if not docker_image_exists(image_name):
            dockerfile = build_default_docker_image(image_name, script_path)
        else:
            dockerfile, image_name = build_extended_docker_image(image_name, script_path)
        # Setup AWS creds: consider better approach
        setup_aws_creds(aws_access_key_id, aws_secret_access_key)

        timestamp = int(time.time())
        container_name = f"{image-name}-container-{timestamp}"
        logger.info(f"Run in a new container {container_name}")
        cmd = (f"docker run --rm --name {container_name} "
               f"--log-driver=awslogs "
               f"--log-opt awslogs-region={aws_region} "
               f"--log-opt awslogs-group={aws_cloudwatch_group} "
               f"--log-opt awslogs-stream={aws_cloudwatch_stream} "
               f"--log-opt awslogs-create-group=true "
               f"-d {image_name}")

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
        return container_name, dockerfile


def main():
    args = get_args()
    container_name, dockerfile_path = run_in_container(args.docker_image,
                                                       args.bash_command,
                                                       args.aws_region,
                                                       args.aws_cloudwatch_group,
                                                       args.aws_cloudwatch_stream,
                                                       args.aws_access_key_id,
                                                       args.aws_secret_access_key)
    # Set signal handlers
    sigint_handler = partial(handle_sigint,
                             container_name=container_name,
                             dockerfile_path=dockerfile_path)

    sigterm_handler = partial(handle_sigterm,
                              container_name=container_name,
                              dockerfile_path=dockerfile_path)

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

