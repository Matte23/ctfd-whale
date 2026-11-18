# 使用指南

## TLDR

如果你从未部署过CTFd，你可以通过执行:

```sh
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh --mirror Aliyun
docker swarm init
docker node update --label-add='name=linux-1' $(docker node ls -q)

git clone https://github.com/CTFd/CTFd --depth=1
git clone https://github.com/frankli0324/ctfd-whale CTFd/CTFd/plugins/ctfd-whale --depth=1
curl -fsSL https://cdn.jsdelivr.net/gh/frankli0324/ctfd-whale/docker-compose.example.yml -o CTFd/docker-compose.yml

# make sure you have pip3 installed on your rig
pip3 install docker-compose
docker-compose -f CTFd/docker-compose.yml up -d
docker-compose -f CTFd/docker-compose.yml exec ctfd python manage.py
```

脚本会在一台Linux机器上安装 ***docker.com版本的*** `docker-ce`，`python3-pip` 以及 `docker-compose`，请确保执行上述代码之前：

* 安装好curl，git，python3以及pip
* 网络环境良好，能正常从GitHub克隆仓库
* 网络环境良好，能正常从Docker Registry拖取镜像

## 手动安装

为了更好地理解ctfd-whale各个组件的作用，更充分地利用ctfd-whale，在真实使用ctfd-whale时建议用户手动、完整地从空白CTFd开始搭建一个实例。下面本文将引导你完成整个流程。

### 从零开始

首先需要初始化一个swarm集群并给节点标注名称

linux节点名称需要以 `linux-` 打头，windows节点则以 `windows-` 打头

```bash
docker swarm init
docker node update --label-add "name=linux-1" $(docker node ls -q)
```

`ctfd-whale`利用`docker swarm`的集群管理能力，能够将题目容器分发到不同的节点上运行。选手每次请求启动题目容器时，`ctfd-whale`都将随机选择一个合适的节点运行这个题目容器。

然后，我们需要确保CTFd可以正常运行。

注意，2.5.0+版本CTFd的 `docker-compose.yml` 中包含了一个 `nginx` 反代，占用了80端口

```bash
git clone https://github.com/CTFd/CTFd --depth=1
cd CTFd  # 注：以下全部内容的cwd均为此目录
```

先将 `docker-compose.yml` 的第一行进行修改，以支持 `attachable` 参数

`version '2'` -> `version '3'`

接着

```bash
docker-compose up -d
```

访问<http://localhost>（或8000端口），对CTFd进行初始配置

### 配置frp

ctfd-whale 使用 **frp 官方镜像**（`fatedier/frps` 与 `fatedier/frpc`），版本
**v0.72.0 或更高**，配置格式为 TOML。插件为每个实例通过 frpc 的 *store* API
创建一个名为 `whale-<容器名>` 的代理；frpc 会立即生效，并将 store 持久化到磁盘，
重启后自动恢复。无需在 frpc 配置中手动列出代理。

示例 compose 文件（`docker-compose.example.yml`）已包含这两个服务。将插件自带的
示例配置复制到 compose 文件旁：

```bash
mkdir -p conf/frp
cp CTFd/plugins/ctfd-whale/docs/frp/frps.toml CTFd/plugins/ctfd-whale/docs/frp/frpc.toml conf/frp/
```

然后修改：

* `auth.token`：两个文件中填写相同的随机值。
* `frpc.toml` 中的 `webServer.password`：强随机密码。**题目容器与 frpc 处于同一网络，
  可以访问其管理端口**，该密码用于防止选手添加或删除路由。
* `frps.toml` 中的 `subDomainHost` 与 `vhostHTTPPort`：指向 frps 的域名，以及 http
  类型题目使用的端口。
* `frps.toml` 中的 `allowPorts`：direct（TCP）类型题目的端口范围，需与插件设置中的
  direct 端口范围及 compose 文件中 frps 映射的端口一致（默认 `10000-10100`）。

```
CTFd/
    conf/
        nginx/
        frp/
            frps.toml
            frpc.toml
    docker-compose.yml
```

执行 `docker compose up -d` 启动，然后查看 `docker compose logs frpc`：

```log
admin server listen on 0.0.0.0:7400
login to server success, get run id [...]
```

### 在CTFd中配置frp路由

在 CTFd 的 **Admin → Config** 中，Plugins 下的 **Whale: Router** 标签页中设置：

* **API URL**：`http://frpc:7400`
* **API User** / **API Password**：`frpc.toml` 中的 `webServer.user` / `webServer.password`
* **Http Domain Suffix** / **External Http Port**：`frps.toml` 中的 `subDomainHost` / `vhostHTTPPort`
* **Direct Minimum/Maximum Port**：`frps.toml` 中 `allowPorts` 的范围

设置页面会检查连接：密码错误，或 frpc 未启用 store（`frpc.toml` 中的 `[store] path`）时会给出提示。

#### 从旧版本 ctfd-whale 升级

旧版本使用 frp 已弃用的 INI 格式、第三方镜像以及 frpc 配置模板设置，并在每次变更时
重写 frpc 的完整配置。升级时：将 frp 服务替换为上述官方镜像与 TOML 配置，然后在插件中
设置 API 用户名与密码。正在运行的实例的代理会在几秒内自动重建。

### 配置CTFd

前面的工作完成后，将本机docker的访问接口映射到CTFd所在容器内

并将CTFd添加到frpc所在network中（注意不是containers这个network）

```yml
services:
    ctfd:
        ...
        volumes:
            - /var/run/docker.sock:/var/run/docker.sock
        depends_on:
            - frpc #frpc需要先运行
        networks:
            ...
            frp_connect:
```

将CTFd-Whale克隆至CTFd的插件目录

```bash
git clone https://github.com/frankli0324/CTFd-Whale CTFd/plugins/ctfd-whale --depth=1
docker-compose build # 需要安装依赖
docker-compose up -d
```

进入 CTFd 的 **Admin → Config**，打开 Plugins 下的 **Whale: …** 标签页（运行中的实例在管理菜单的 **Instances** 中），首先配置docker配置项

需要注意的是 `Auto Connect Network` ，如果按照上面的配置流程进行配置的话，应当是 `ctfd_containers`（默认值）

如果不确定的话，可以通过下面的命令列出CTFd目录compose生成的所有network

```bash
docker network ls -f "label=com.docker.compose.project=ctfd" --format "{{.Name}}"
```

然后检查frp配置项是否正确：参见上文「在CTFd中配置frp路由」。

### 配置nginx

如果你在使用2.5.0+版本的CTFd，那么你可以直接利用自带的nginx进行http题目的反代

首先去除docker-compose.yml中对frps http端口的映射(8001)
如果想贯彻到底的话，可以

* 为nginx添加internal与default两个network
* 去除CTFd的default network，并去除ports项

在 `./conf/nginx/nginx.conf` 的http block中添加以下server block

```conf
server {
  listen 80;
  server_name *.node3.buuoj.cn;
  location / {
    proxy_pass http://frps:8001;
    proxy_redirect off;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Host $server_name;
  }
}
```

## 部署题目

### 单容器题目环境

请参考<https://github.com/CTFTraining>中的镜像进行题目镜像制作（Dockerfile编写）。总体而言，题目在启动时会向**容器**内传入名为 `FLAG` 的环境变量，你需要编写一个启动脚本（一般为bash+sed组合拳）将flag写入自己的题目中，并删除这一环境变量。

请出题人制作镜像时请理清思路，不要搞混容器与镜像的概念。这样既方便自己，也方便部署人员。

### 多容器题目环境

在题目镜像名处填写一个json object，即可创建一道多容器的题目

```json
{
    "hostname": "image",
}
```

Whale会保留json的key顺序，并将第一个容器作为"主容器"映射到外网，映射方式与单容器相同
以buuoj上的swpu2019 web2为例，可以配置如下：

```json
{
    "ss": "shadowsocks-chall",
    "web": "swpu2019-web2",
    ...
}
```

其中shadowsocks-chall的Dockerfile:

```dockerfile
FROM shadowsocks/shadowsocks-libev
ENV PASSWORD=123456
ENV METHOD=aes-256-cfb
```

> 注：由于写README的并不是buuoj管理员，故上述仅作说明用，与实际情况可能有较大出入

## 安全事项

* 请不要将管理员账号给不可信第三方：管理员可以决定在 Docker 主机上运行哪些镜像。（flag 与子域名模板在 Jinja 沙箱中渲染。）
* 题目容器与 frpc 处于同一网络，可以访问其管理 API：请务必在 `frpc.toml` 中设置强随机的 `webServer.password`，并在插件 Router 设置中填写相同的密码。
* 访问 Docker API 等同于拥有 Docker 主机的 root 权限：请相应地保护 CTFd 与主机。

## 高级部署

用于下发靶机实例的服务器与运行 `CTFd` 网站的服务器分离，`CTFd-whale` 通过启用了 `TLS/SSL` 验证的 `Dockers API`进行下发容器控制

参见 [advanced.zh-cn.md](advanced.zh-cn.md)