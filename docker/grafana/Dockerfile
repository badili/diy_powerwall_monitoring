FROM grafana/grafana:7.1.3
# ADD ./provisioning /etc/grafana/provisioning
# ADD ./dashboards /var/lib/grafana/dashboards

USER root
RUN apk add --no-cache tzdata
RUN ln -snf /usr/share/zoneinfo/Africa/Nairobi /etc/localtime
RUN echo "Africa/Nairobi" > /etc/timezone

ENV DS_DB "grafana"
