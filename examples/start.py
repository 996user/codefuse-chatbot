import docker, sys, os, time, requests, psutil
import subprocess
from docker.types import Mount, DeviceRequest
from loguru import logger

src_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.append(src_dir)

from configs.model_config import USE_FASTCHAT
from configs.server_config import (
    NO_REMOTE_API, SANDBOX_SERVER, SANDBOX_IMAGE_NAME, SANDBOX_CONTRAINER_NAME, 
    WEBUI_SERVER, API_SERVER, SDFILE_API_SERVER, CONTRAINER_NAME, IMAGE_NAME, DOCKER_SERVICE,
    DEFAULT_BIND_HOST,
)


import platform
system_name = platform.system()
USE_TTY = system_name in ["Windows"]


def check_process(content: str, lang: str = None, do_stop=False):
    '''process-not-exist is true, process-exist is false'''
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        # check process name contains "jupyter" and port=xx

        # if f"port={SANDBOX_SERVER['port']}" in str(process.info["cmdline"]).lower() and \
        #     "jupyter" in process.info['name'].lower():
        if content in str(process.info["cmdline"]).lower():
            logger.info(f"content, {process.info}")
            # 关闭进程
            if do_stop:
                process.terminate()
                return True
            return False
    return True

def check_docker(client, container_name, do_stop=False):
    '''container-not-exist is true, container-exist is false'''
    for i  in client.containers.list(all=True):
        if i.name == container_name:
            if do_stop:
                container = i
                container.stop()
                container.remove()
                return True
            return False
    return True

def start_docker(client, script_shs, ports, image_name, container_name, mounts=None, network=None):
    container = client.containers.run(
        image=image_name,
        command="bash",
        mounts=mounts,
        name=container_name,
        # device_requests=[DeviceRequest(count=-1, capabilities=[['gpu']])],
        # network_mode="host",
        ports=ports,
        stdin_open=True,
        detach=True,
        tty=USE_TTY,
        network=network,   
    )

    logger.info(f"docker id: {container.id[:10]}")

    # 启动notebook
    for script_sh in script_shs:
        if USE_FASTCHAT and "llm_api" in script_sh:
            logger.debug(script_sh)
            response = container.exec_run(["sh", "-c", script_sh])
            logger.debug(response)
        elif "llm_api" not in script_sh:
            logger.debug(script_sh)
            response = container.exec_run(["sh", "-c", script_sh])
            logger.debug(response)
    return container

#########################################
############# 开始启动服务 ###############
#########################################

client = docker.from_env()
client.containers.run
network_name ='my_network'

def start_sandbox_service():
    networks = client.networks.list()
    if any([network_name==i.attrs["Name"] for i in networks]):
        network = client.networks.get(network_name)
    else:
        network = client.networks.create('my_network', driver='bridge')

    mount = Mount(
            type='bind',
            source=os.path.join(src_dir, "jupyter_work"),
            target='/home/user/chatbot/jupyter_work',
            read_only=False  # 如果需要只读访问，将此选项设置为True
        )
    mounts = [mount]
    # 沙盒的启动与服务的启动是独立的
    if SANDBOX_SERVER["do_remote"]:
        # 启动容器
        logger.info("start container sandbox service")
        script_shs = ["bash jupyter_start.sh"]
        JUPYTER_WORK_PATH = "/home/user/chatbot/jupyter_work"
        script_shs = [f"cd /home/user/chatbot/jupyter_work && nohup jupyter-notebook --NotebookApp.token=mytoken --port=5050 --allow-root --ip=0.0.0.0 --notebook-dir={JUPYTER_WORK_PATH} --no-browser --ServerApp.disable_check_xsrf=True &"]
        ports = {f"{SANDBOX_SERVER['docker_port']}/tcp": f"{SANDBOX_SERVER['port']}/tcp"}
        if check_docker(client, SANDBOX_CONTRAINER_NAME, do_stop=True, ):
            container = start_docker(client, script_shs, ports, SANDBOX_IMAGE_NAME, SANDBOX_CONTRAINER_NAME, mounts=mounts, network=network_name)
        # 判断notebook是否启动
        time.sleep(5)
        retry_nums = 3
        while retry_nums>0:
            logger.info(f"http://localhost:{SANDBOX_SERVER['port']}")
            response = requests.get(f"http://localhost:{SANDBOX_SERVER['port']}", timeout=270)
            if response.status_code == 200:
                logger.info("container & notebook init success")
                break
            else:
                retry_nums -= 1
                logger.info(client.containers.list())
                logger.info("wait container running ...")
            time.sleep(5)

    else:
        check_docker(client, SANDBOX_CONTRAINER_NAME, do_stop=True, )
        logger.info("start local sandbox service")

def start_api_service(sandbox_host=DEFAULT_BIND_HOST):
    # 启动service的容器
    if DOCKER_SERVICE:
        logger.info("start container service")
        check_process("service/api.py", do_stop=True)
        check_process("service/sdfile_api.py", do_stop=True)
        check_process("service/sdfile_api.py", do_stop=True)
        check_process("webui.py", do_stop=True)
        mount = Mount(
            type='bind',
            source=src_dir,
            target='/home/user/chatbot/',
            read_only=False  # 如果需要只读访问，将此选项设置为True
        )
        mount_database = Mount(
            type='bind',
            source=os.path.join(src_dir, "knowledge_base"),
            target='/home/user/knowledge_base/',
            read_only=False  # 如果需要只读访问，将此选项设置为True
        )

        ports={
                f"{API_SERVER['docker_port']}/tcp": f"{API_SERVER['port']}/tcp", 
                f"{WEBUI_SERVER['docker_port']}/tcp": f"{WEBUI_SERVER['port']}/tcp",
                f"{SDFILE_API_SERVER['docker_port']}/tcp": f"{SDFILE_API_SERVER['port']}/tcp",
                }
        mounts = [mount, mount_database]
        script_shs = [
            "mkdir -p /home/user/logs",
            "pip install zdatafront-sdk-python -i https://artifacts.antgroup-inc.cn/simple",
            "pip install jsonref",
            "pip install javalang",
            "nohup python chatbot/dev_opsgpt/service/sdfile_api.py > /home/user/logs/sdfile_api.log 2>&1 &",
            f"export DUCKDUCKGO_PROXY=socks5://host.docker.internal:13659 && export SANDBOX_HOST={sandbox_host} &&\
                nohup python chatbot/dev_opsgpt/service/api.py > /home/user/logs/api.log 2>&1 &",
            "nohup python chatbot/dev_opsgpt/service/llm_api.py > /home/user/  2>&1 &",
            f"export DUCKDUCKGO_PROXY=socks5://host.docker.internal:13659 && export SANDBOX_HOST={sandbox_host} &&\
                cd chatbot/examples && nohup streamlit run webui.py > /home/user/logs/start_webui.log 2>&1 &"
            ]
        if check_docker(client, CONTRAINER_NAME, do_stop=True):
            container = start_docker(client, script_shs, ports, IMAGE_NAME, CONTRAINER_NAME, mounts, network=network_name)

    else:
        logger.info("start local service")
        # 关闭之前启动的docker 服务
        # check_docker(client, CONTRAINER_NAME, do_stop=True, )

        api_sh = "nohup python ../dev_opsgpt/service/api.py > ../logs/api.log 2>&1 &"
        sdfile_sh = "nohup python ../dev_opsgpt/service/sdfile_api.py > ../logs/sdfile_api.log 2>&1 &"
        llm_sh = "nohup python ../dev_opsgpt/service/llm_api.py > ../logs/llm_api.log 2>&1 &"
        webui_sh = "streamlit run webui.py" if USE_TTY else "streamlit run webui.py"
        #
        if not NO_REMOTE_API and check_process("service/api.py"):
            subprocess.Popen(api_sh, shell=True)
        # 
        if USE_FASTCHAT and check_process("service/llm_api.py"):
            subprocess.Popen(llm_sh, shell=True)
        # 
        if check_process("service/sdfile_api.py"):
            subprocess.Popen(sdfile_sh, shell=True)

        subprocess.Popen(webui_sh, shell=True)



if __name__ == "__main__":
    start_sandbox_service()
    client = docker.from_env()
    containers = client.containers.list(all=True)

    sandbox_host = DEFAULT_BIND_HOST
    for container in containers:
        container_a_info = client.containers.get(container.id)
        if container_a_info.name == SANDBOX_CONTRAINER_NAME:
            container1_networks = container.attrs['NetworkSettings']['Networks']
            sandbox_host = container1_networks.get(network_name)["IPAddress"]
            break
    start_api_service(sandbox_host)
