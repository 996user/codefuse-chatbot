From python:3.9.18-bookworm

WORKDIR /home/user

COPY ./requirements.txt /home/user/docker_requirements.txt
COPY ./jupyter_start.sh /home/user/jupyter_start.sh


RUN apt-get update
RUN apt-get install -y iputils-ping telnetd net-tools vim tcpdump
# RUN echo telnet stream tcp nowait telnetd /usr/sbin/tcpd /usr/sbin/in.telnetd /etc/inetd.conf
# RUN service inetutils-inetd start
# service inetutils-inetd status


RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install -r /home/user/docker_requirements.txt

CMD ["bash"]
