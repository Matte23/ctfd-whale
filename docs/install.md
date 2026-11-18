# Installation & Usage Guide

## TLDR

If you never deployed a CTFd instance before:

```sh
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
docker swarm init
docker node update --label-add='name=linux-1' $(docker node ls -q)

git clone https://github.com/CTFd/CTFd --depth=1
git clone https://github.com/frankli0324/ctfd-whale CTFd/CTFd/plugins/ctfd-whale --depth=1
curl -fsSL https://cdn.jsdelivr.net/gh/frankli0324/ctfd-whale/docker-compose.example.yml -o CTFd/docker-compose.yml

# make sure you have pip3 installed on your rig
pip3 install docker-compose
docker-compose -f CTFd/docker-compose.yml up -d
# wait till the containers are ready
docker-compose -f CTFd/docker-compose.yml exec ctfd python manage.py set_config whale:auto_connect_network
```

The commands above tries to install `docker-ce`，`python3-pip` and `docker-compose`. Make sure the following requirements are satisfied before you execute them:

* have `curl`, `git`, `python3` and `pip` installed
* GitHub is reachable
* Docker Registry is reachable

## Installation

### Start from scratch

First of all, you should initialize a docker swarm and label the nodes

names of nodes running linux/windows should begin with `linux/windows-*`

```bash
docker swarm init
docker node update --label-add "name=linux-1" $(docker node ls -q)
```

Taken advantage of the orchestration ability of `docker swarm`, `ctfd-whale` is able to distribute challenge containers to different nodes(machines). Each time a user request for a challenge container, `ctfd-whale` will randomly pick a suitable node for running the container.

After initializing a swarm, make sure that CTFd runs as expected on your PC/server

Note that the included compose file in CTFd 2.5.0+ starts an nginx container by default, which takes the http/80 port. make sure there's no conflicts.

```bash
git clone https://github.com/CTFd/CTFd --depth=1
cd CTFd  # the cwd will not change throughout this guide from this line on
```

Change the first line of `docker-compose.yml` to support `attachable` property

`version '2'` -> `version '3'`

```bash
docker-compose up -d
```

take a look at <http://localhost>(or port 8000) and setup CTFd

### Configure frp

ctfd-whale uses the **official frp images** (`fatedier/frps` and
`fatedier/frpc`), **v0.72.0 or later**, configured in TOML. For each instance
the plugin creates one proxy, named `whale-<container>`, through frpc's
*store* API; frpc applies it immediately and keeps the store on disk across
restarts. Nothing has to be listed in frpc's config by hand.

The example compose file (`docker-compose.example.yml`) already contains both
services. Copy the example configs shipped with the plugin next to the
compose file:

```bash
mkdir -p conf/frp
cp CTFd/plugins/ctfd-whale/docs/frp/frps.toml CTFd/plugins/ctfd-whale/docs/frp/frpc.toml conf/frp/
```

then edit them:

* `auth.token`: the same random value in both files.
* `webServer.password` in `frpc.toml`: a strong random value. **The challenge
  containers share a network with frpc and can reach its admin port**, so this
  password is what keeps players from adding or removing routes.
* `subDomainHost` and `vhostHTTPPort` in `frps.toml`: the domain whose
  subdomains point to frps, and the port HTTP challenges are served on.
* `allowPorts` in `frps.toml`: the port range for "direct" (TCP) challenges.
  It must match the plugin's direct port range and the ports published for
  frps in the compose file (`10000-10100` by default).

```
CTFd/
    conf/
        nginx/
        frp/
            frps.toml
            frpc.toml
    docker-compose.yml
```

Start the stack with `docker compose up -d`, then check `docker compose logs frpc`:

```log
admin server listen on 0.0.0.0:7400
login to server success, get run id [...]
```

### Configure the frp router in CTFd

In the plugin's settings (`Docker` in the admin menu), tab **Router**, set:

* **API URL**: `http://frpc:7400`
* **API User** / **API Password**: `webServer.user` / `webServer.password` of `frpc.toml`
* **Http Domain Suffix** / **External Http Port**: `subDomainHost` / `vhostHTTPPort` of `frps.toml`
* **Direct Minimum/Maximum Port**: the `allowPorts` range of `frps.toml`

The settings page checks the connection: it reports a wrong password, or a
frpc without the store enabled (`[store] path` in `frpc.toml`).

#### Upgrading from older ctfd-whale versions

Older versions used frp's deprecated INI format, third-party images and a
frpc config template setting, rewriting frpc's whole config on every change.
To upgrade: replace the frp services with the official images and the TOML
configs above, then set the API user and password in the plugin. The proxies
of running instances are re-created automatically within a few seconds.

### Configure CTFd

After finishing everything above:

* map docker socket into CTFd container
* Attach CTFd container to frp_connect

```yml
services:
    ctfd:
        ...
        volumes:
            - /var/run/docker.sock:/var/run/docker.sock
        depends_on:
            - frpc #need frpc to run ahead
        networks:
            ...
            frp_connect:
```

and then clone Whale into CTFd plugins directory (yes, finally)

```bash
git clone https://github.com/frankli0324/CTFd-Whale CTFd/plugins/ctfd-whale --depth=1
docker-compose build # for pip to find requirements.txt
docker-compose up -d
```

go to the Whale Configuration page (`/plugins/ctfd-whale/admin/settings`)

#### Docker related configs

`Auto Connect Network`, if you strictly followed the guide, should be `ctfd_containers` (the default)

If you're not sure about that, this command lists all networks in the current stack

```bash
docker network ls -f "label=com.docker.compose.project=ctfd" --format "{{.Name}}"
```

#### frp related configs

See [Configure the frp router in CTFd](#configure-the-frp-router-in-ctfd).

Whale should be kinda usable at this moment.

### Configure nginx

If you are using CTFd 2.5.0+, you can utilize the included nginx.

remove the port mapping rule for frps vhost http port(8001) in the compose file

If you wnat to go deeper:

* add nginx to `default` and `internal` network
* remove CTFd from `default` and remove the mapped 8000 port

add following server block to `./conf/nginx/nginx.conf`:

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

## Challenge Deployment

### Standalone Containers

Take a look at <https://github.com/CTFTraining>

In one word, a `FLAG` variable will be passed into the container when it's started. You should write your own startup script (usually with bash and sed) to:

* replace your flag with the generated flag
* remove or override the `FLAG` variable

PLEASE create challenge images with care.

### Grouped Containers

"name" the challenge image with a json object, for example:

```json
{
    "hostname": "image",
}
```

Whale will keep the order of the keys in the json object, and take the first image as the "main container" of a challenge. The "main container" will be mapped to frp with same rules from standalone containers

see how grouped containers are created in the [code](utils/docker.py#L58)

## Security

* Only give the admin account to trusted people: admins control which images run on your Docker host. (Flag and subdomain templates run in a Jinja sandbox.)
* Challenge containers share a network with frpc and can reach its admin API: always set a strong `webServer.password` in `frpc.toml`, and the same password in the plugin's Router settings.
* Access to the Docker API is equivalent to root on the Docker host: protect CTFd, and the host, accordingly.

## Advanced Deployment

To separate the target server (for lunching instance) and CTFd web server with TLS secured docker API, please refer to [this document](advanced.md)