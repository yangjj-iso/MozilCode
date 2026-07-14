# 使用本地已有基础镜像，避免拉 eclipse-temurin（国内网络常卡住）
FROM postgres:15-alpine
USER root
RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories \
  && apk add --no-cache openjdk21-jre-headless
WORKDIR /app
COPY target/mozilcode-cloud-0.1.0.jar /app/app.jar
EXPOSE 8000
ENTRYPOINT ["java", "-jar", "/app/app.jar"]