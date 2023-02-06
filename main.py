"""Redirect container logs to AWS Cloudwatch."""
import argparse
import subprocess
import typing as t
from jinja2 import Environment, FileSystemLoader, select_autoescape


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


def create_python_dockerfile(bash_command: str,
                             aws_access_key_id: str,
                             aws_secret_access_key: str) -> None:
    """Create Dockerfile from Jinja template."""
    env = Environment(loader=FileSystemLoader('templates/'),
                      autoescape=select_autoescape())
    template = env.get_template("Dockerfile.template.jinja")
    stream = template.stream(bash_command=bash_command,
                             aws_access_key_id=aws_access_key_id,
                             aws_secret_access_key=aws_secret_access_key)
    stream.dump('Dockerfile')


def create_docker_image(image_name: str,
                        bash_command: str,
                        aws_access_key_id: str,
                        aws_secret_access_key: str) -> t.Tuple[bytes, bytes, int]:
    create_python_dockerfile(bash_command,
                             aws_access_key_id,
                             aws_secret_access_key)
    # Build and wait for finish
    cmd = f"sudo docker build -t {image_name} ."
    result = subprocess.run(cmd, shell=True, check=True, capture_output=True)
    # TODO: Consider logging here
    print(result.stdout)
    print(f"Build finished with exit code: {result.returncode}")
    #
    return result.stdout, result.stderr, result.returncode


def docker_image_exists(image_name: str) -> bool:
    """Check whether docker image with specified name exists"""
    pass


def run_container(image_name: str,
                  bash_command: str,
                  aws_region: str,
                  aws_cloudwatch_group: str,
                  aws_cloudwatch_stream: str,
                  aws_access_key_id: str,
                  aws_secret_access_key: str) -> None:
    """Run bash command in a docker container from image name. Will be created if doesn't exist."""
    if not docker_image_exists(image_name):
        create_docker_image(image_name, bash_command,
                            aws_access_key, aws_secret_access_key)
    # now run container from created process with AWS redirection...
    cmd = (f"sudo docker run --name {image_name}-container -d {image_name} "
           f"--log-driver=awslogs "
           f"--log-opt awslogs-region={aws_region} "
           f"--log-opt awslogs-group={aws_cloudwatch_group} "
           f"--log-opt awslogs-stream={aws_cloudwatch_stream} "
           f"--log-opt awslogs-create-group=true ")
    result = subprocess.run(cmd, shell=True, check=True, capture_output=True)
    #
    print(result.stdout)
    print(f"Finished with exit code: {result.returncode}")


def main():
    args = get_args()
    run_container(args.image_name, args.bash_command,
                  args.aws_region,
                  args.aws_cloudwatch_group,
                  args.aws_cloudwatch_stream,
                  args.aws_access_key_id,
                  args.aws_secret_access_key)


if __name__ == '__main__':
    main()
