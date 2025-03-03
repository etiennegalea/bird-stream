FROM ubuntu:22.04

RUN apt update
RUN apt install coturn -y

# RUN sed -i "s/USER=turnserver/USER=root/" /etc/init.d/coturn
# RUN sed -i "s/GROUP=turnserver/GROUP=root/" /etc/init.d/coturn
RUN sed -i "s/#TURNSERVER_ENABLED=1/TURNSERVER_ENABLED=1/" /etc/default/coturn

# Create a directory for logs
RUN mkdir -p /var/log/coturn && \
    touch /var/log/coturn/turnserver.log && \
    chmod -R 755 /var/log/coturn

# Start coturn with logging enabled
CMD turnserver -v --log-file=/var/log/coturn/turnserver.log --no-stdout-log=0 && tail -f /var/log/coturn/turnserver.log