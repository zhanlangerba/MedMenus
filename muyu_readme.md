# 启动redis

cd D:\Redis-7.0.8-Windows-x64-msys2
redis-server redis.conf --requirepass snowball2019


user_id: "abc123"
  └── project_id: "proj-001" 
      └── thread_id: "thread-001" (= session_id)
          ├── message_id: "msg-001" (用户输入)
          ├── message_id: "msg-002" (AI回复)
          └── invocation_id: "inv-001" (整个对话轮次)
              
agent_id: "agent-001" (配置哪个AI助手)
instance_id: "inst-001" (哪个后端服务器在处理)


后台启动：dramatiq run_agent_background



# sandbox 部署文档：
https://docs.app.codeanywhere.com/installation/single-node/
https://www.daytona.io/docs/en/sandbox-management/



安装 go：https://blog.csdn.net/five_east_west/article/details/134874738
# 3. 下载依赖
go mod tidy
make build OS=linux


1. 下载并设置FRPS
# 下载FRP
curl -L https://github.com/fatedier/frp/releases/download/v0.60.0/frp_0.60.0_linux_amd64.tar.gz -o /tmp/frp.tar.gz
cd /tmp && tar -xzf frp.tar.gz
cd frp_0.60.0_linux_amd64

# 创建FRPS配置文件
cd /tmp/frp_0.60.0_linux_amd64
cat > frps.toml << 'EOF'
bindAddr = "0.0.0.0"
bindPort = 7000
vhostHTTPPort = 8080
vhostHTTPSPort = 8443
subDomainHost = "localhost"

[webServer]
addr = "0.0.0.0"
port = 7500
user = "admin"
password = "admin123"
EOF

./frps -c frps.toml &

export DEFAULT_FRPS_DOMAIN="127.0.0.1" && export DEFAULT_FRPS_PROTOCOL="http" && export DEFAULT_FRPS_PORT="7000" && echo "环境变量已设置: $DEFAULT_FRPS_DOMAIN:$DEFAULT_FRPS_PORT ($DEFAULT_FRPS_PROTOCOL)"

ls -la ~/.config/daytona/server/binaries/v0.0.0-dev/

  cd /c/Users/Administrator/Desktop/daytona-0.49.0
   export DEFAULT_FRPS_DOMAIN="127.0.0.1"
   export DEFAULT_FRPS_PROTOCOL="http"
   export DEFAULT_FRPS_PORT="7000"
   ~/.config/daytona/server/binaries/v0.0.0-dev/daytona-linux-amd64 serve


root@4U:~# ~/.config/daytona/server/binaries/v0.0.0-dev/daytona-linux-amd64 profile add
Profile muyu added and set as active
Server URL: http://localhost:3986






   
### ✅ 最新的安装方法（Docker 本地部署）

#### 1. 克隆 Daytona 仓库

首先，克隆 Daytona 的 GitHub 仓库：

```bash
git clone https://github.com/daytonaio/daytona.git

cd daytona
```



#### 2. 构建 Docker 镜像

在仓库根目录下，使用以下命令构建 Docker 镜像：

```bash
sudo systemctl status docker
docker build -t daytona -f images/sandbox/Dockerfile .

make image
```




# python sdk

pip install daytona


如果您希望将镜像推送到特定的容器注册表，可以使用：

```bash
REGISTRY=gcr.io/supa-fast-c432 make push-image
```



#### 3. 启动 Daytona 服务

构建完成后，启动 Daytona 服务：([Arm 学习路径][1])

```bash
./daytona serve
```



这将启动 Daytona 的本地开发环境管理服务。

#### 4. 配置 Git 提供商

Daytona 支持 GitHub、GitLab、Bitbucket 等平台。使用以下命令添加 Git 提供商：

```bash
daytona git-providers add
```



按照提示完成配置。

#### 5. 设置目标环境

Daytona 支持多种目标环境，包括 Docker。使用以下命令设置目标环境：

```bash
daytona target set
```



选择 Docker 作为目标环境。([GitHub][2])

#### 6. 创建开发环境

使用以下命令创建开发环境：

```bash
daytona create --no-ide https://github.com/microsoft/vscode-remote-try-python/tree/main
```



这将从指定的 Git 仓库创建一个开发环境。

#### 7. 连接开发环境

创建完成后，您可以使用以下命令连接到开发环境：

```bash
daytona code
```



这将启动 VS Code 并连接到您的开发环境。

---

### 📚 参考资料

* [Daytona GitHub 仓库](https://github.com/daytonaio/daytona)
* [Daytona Docker Provider](https://github.com/daytonaio/daytona-provider-docker)
* [Daytona Docker Extension](https://github.com/daytonaio/daytona-docker-extension)

---

如果您在部署过程中遇到任何问题，欢迎随时提问，我将竭诚为您解答。

[1]: https://learn.arm.com/learning-paths/cross-platform/daytona/install/?utm_source=chatgpt.com "Install Daytona and run the server"
[2]: https://github.com/daytonaio/daytona?utm_source=chatgpt.com "Daytona is a Secure and Elastic Infrastructure for Running ..."
